// Same rules as deepsift_sdk.detect.detect_type, so the GUI shows what the gateway
// will pick before the run starts.
import type { EntityType } from "./api";

const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
const PHONE = /^\+?[\d\s().-]+$/;
const DOMAIN = /^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}\.?$/i;

export function detectType(selector: string): EntityType {
  const value = selector.trim();
  if (/^https?:\/\//i.test(value)) return "url";
  if (value.startsWith("blob:")) return "image";
  if (EMAIL.test(value)) return "email";
  const digits = value.replace(/\D/g, "").length;
  if (PHONE.test(value) && digits >= 7 && digits <= 15) return "phone";
  if (DOMAIN.test(value)) return "domain";
  return "username";
}
