// What WhatsApp tells any account about a phone number. Only what the owner's privacy
// settings make visible comes back: a hidden picture or "about" is simply absent.

const E164 = /^\+[1-9]\d{6,14}$/;

export function toE164(value) {
  const cleaned = String(value).replace(/[^\d+]/g, "");
  return E164.test(cleaned) ? cleaned : null;
}

async function optional(promise) {
  try {
    return await promise;
  } catch {
    return undefined; // hidden by privacy settings, absent, or not allowed
  }
}

/**
 * @param sock a connected Baileys socket (or a fake with the same methods)
 * @param {string} e164 phone number, +country code
 * @param {{picture: boolean, about: boolean, business: boolean}} want
 */
export async function lookup(sock, e164, want) {
  const results = (await sock.onWhatsApp(e164.slice(1))) ?? [];
  const match = results.find((r) => r.exists);
  if (!match) return { exists: false };

  const jid = match.jid;
  const found = { exists: true, jid };

  if (want.picture) {
    const url = await optional(sock.profilePictureUrl(jid, "image", 15_000));
    if (url) found.picture = url;
  }
  if (want.about) {
    const list = await optional(sock.fetchStatus(jid));
    const status = list?.[0]?.status;
    if (status?.status) {
      found.about = status.status;
      if (status.setAt instanceof Date && status.setAt.getTime() > 0) {
        found.aboutSetAt = status.setAt.toISOString();
      }
    }
  }
  if (want.business) {
    const profile = await optional(sock.getBusinessProfile(jid));
    if (profile) found.business = profile;
  }
  return found;
}
