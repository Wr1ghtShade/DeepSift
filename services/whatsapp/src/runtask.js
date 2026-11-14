// Runs one contract task: limiter, lookup, then entities as events.

import { ErrorCode, ServiceError, checkTask, entity, events } from "./contract.js";
import { toE164, lookup } from "./lookup.js";
import { manifest, option } from "./manifest.js";

const CONFIDENCE = 0.95; // WhatsApp itself confirms the number is registered

function profileAttributes(e164, found) {
  const attributes = { site: "WhatsApp", phone: e164, picture_visible: Boolean(found.picture) };
  if (found.about) attributes.about = found.about;
  if (found.aboutSetAt) attributes.about_set_at = found.aboutSetAt;
  attributes.business = Boolean(found.business);
  const b = found.business;
  if (b) {
    if (b.category) attributes.business_category = b.category;
    if (b.description) attributes.business_description = b.description;
    if (b.address) attributes.business_address = b.address;
    if (b.website?.length) attributes.business_website = b.website;
  }
  return attributes;
}

/**
 * @param task a contract task
 * @param deps.getSock returns a connected socket
 * @param deps.limiterFor (limits) => object with acquire()
 * @param deps.emit async (event) => void
 */
export async function runTask(task, { getSock, limiterFor, emit }) {
  const ev = events(task, manifest.name);
  await emit(ev.started());
  try {
    checkTask(task);
    if (task.input.type !== "phone") {
      throw new ServiceError(ErrorCode.INVALID_INPUT, `whatsapp does not accept ${task.input.type}`);
    }
    const e164 = toE164(task.input.value);
    if (!e164) {
      throw new ServiceError(
        ErrorCode.INVALID_INPUT,
        "number must be in international format, e.g. +33612345678",
      );
    }

    const limiter = limiterFor({
      minInterval: option(task, "min_interval"),
      dailyLimit: option(task, "daily_limit"),
    });
    const sock = await getSock(); // fails fast when nothing is linked, before using the quota
    const { remaining } = await limiter.acquire();
    const found = await lookup(sock, e164, {
      picture: Boolean(option(task, "fetch_picture")),
      about: Boolean(option(task, "fetch_about")),
      business: Boolean(option(task, "fetch_business")),
    });

    let count = 0;
    if (!found.exists) {
      await emit(ev.progress(1, 1, `no WhatsApp account (${remaining} lookups left today)`));
    } else {
      const profile = entity(
        "profile",
        `https://wa.me/${e164.slice(1)}`,
        profileAttributes(e164, found),
        CONFIDENCE,
      );
      await emit(ev.entity(profile, task.input.id, "found_on"));
      count += 1;
      if (found.picture) {
        const image = entity("image", found.picture, { site: "WhatsApp", role: "avatar" }, CONFIDENCE);
        await emit(ev.entity(image, profile.id, "avatar"));
        count += 1;
      }
      const email = found.business?.email;
      if (email) {
        const mail = entity("email", String(email).trim().toLowerCase(), { site: "WhatsApp Business" }, 0.8);
        await emit(ev.entity(mail, profile.id, "business_email"));
        count += 1;
      }
      await emit(ev.progress(1, 1, `${remaining} lookups left today`));
    }
    await emit(ev.completed(count));
  } catch (error) {
    if (error instanceof ServiceError) {
      await emit(ev.failed(error));
    } else {
      await emit(
        ev.failed({ code: ErrorCode.UPSTREAM_ERROR, message: `whatsapp: ${error.message}`, retryable: true }),
      );
    }
  }
}
