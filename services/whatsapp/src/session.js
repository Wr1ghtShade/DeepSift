// The linked WhatsApp session: one dedicated account, linked once like WhatsApp Web.

import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

import makeWASocket, { Browsers, DisconnectReason, useMultiFileAuthState } from "baileys";
import pino from "pino";

import { ErrorCode, ServiceError } from "./contract.js";

const logger = pino({ level: process.env.DEEPSIFT_WA_LOG ?? "silent" });

export function authDirOf(dataDir) {
  return join(dataDir, "auth");
}

/** True once a device has been linked (creds saved and registered). */
export function isLinked(dataDir) {
  const file = join(authDirOf(dataDir), "creds.json");
  if (!existsSync(file)) return false;
  try {
    const creds = JSON.parse(readFileSync(file, "utf8"));
    return Boolean(creds.registered || creds.me?.id);
  } catch {
    return false;
  }
}

/**
 * Opens a connection and resolves with the socket once it is open.
 * @param {string} dataDir
 * @param {{onQr?: (qr: string) => void, pairingPhone?: string, timeoutMs?: number}} options
 */
export async function connect(dataDir, options = {}) {
  const { onQr, pairingPhone, timeoutMs = 60_000 } = options;
  const { state, saveCreds } = await useMultiFileAuthState(authDirOf(dataDir));

  return new Promise((resolve, reject) => {
    let settled = false;
    let current;
    let pairingAsked = false;
    const timer = setTimeout(() => {
      finish(new ServiceError(ErrorCode.TIMEOUT, "WhatsApp connection timed out"));
    }, timeoutMs);

    const finish = (error, sock) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      if (error) {
        close(current);
        reject(error);
      } else {
        resolve(sock);
      }
    };

    const open = () => {
      const sock = makeWASocket({
        auth: state,
        logger,
        browser: Browsers.ubuntu("DeepSift"),
        markOnlineOnConnect: false, // stay invisible: no "online" presence
        syncFullHistory: false,
        shouldSyncHistoryMessage: () => false,
      });
      current = sock;
      sock.ev.on("creds.update", saveCreds);
      sock.ev.on("connection.update", async (update) => {
        const { connection, lastDisconnect, qr } = update;
        if (qr && pairingPhone && !pairingAsked && !state.creds.registered) {
          pairingAsked = true;
          try {
            const code = await sock.requestPairingCode(pairingPhone.replace(/\D/g, ""));
            onQr?.({ pairingCode: code });
          } catch (error) {
            finish(new ServiceError(ErrorCode.UPSTREAM_ERROR, `pairing failed: ${error.message}`));
          }
        } else if (qr && !pairingPhone) {
          onQr ? onQr({ qr }) : finish(notLinked());
        }
        if (connection === "open") finish(null, sock);
        if (connection === "close") {
          const status = lastDisconnect?.error?.output?.statusCode;
          if (status === DisconnectReason.restartRequired) {
            open(); // normal right after linking
          } else if (status === DisconnectReason.loggedOut) {
            finish(notLinked("the linked device was logged out"));
          } else if (!settled) {
            finish(
              new ServiceError(
                ErrorCode.UPSTREAM_ERROR,
                `WhatsApp closed the connection (${status ?? "no status"})`,
              ),
            );
          }
        }
      });
      return sock;
    };
    open();
  });
}

function notLinked(reason = "no WhatsApp account is linked") {
  return new ServiceError(
    ErrorCode.NEEDS_CONFIG,
    `${reason}: run "deepsift-whatsapp link" with a dedicated account`,
  );
}

export async function close(sock) {
  try {
    sock?.end(undefined);
  } catch {
    // already closed
  }
}
