import { describe, expect, it } from "vitest";
import { detectType } from "./detect";

describe("detectType", () => {
  it.each([
    ["nightowl_77", "username"],
    ["n.owl@example.org", "email"],
    ["+33 6 12 34 56 78", "phone"],
    ["example-shop.fr", "domain"],
    ["https://github.com/x", "url"],
    ["blob:" + "a".repeat(64), "image"],
    ["12345", "username"],
  ])("%s is a %s", (value, type) => {
    expect(detectType(value)).toBe(type);
  });
});
