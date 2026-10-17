import { describe, it, expect } from "vitest";
import { parseSeconds, formatTime, validateFile, isSafeHttpUrl, VERDICT_LABEL } from "./api";

describe("api helpers", () => {
  it("accepts only .mov", () => {
    expect(validateFile(new File(["x"], "a.MOV"))).toBeNull();
    expect(validateFile(new File(["x"], "a.mp4"))).not.toBeNull();
  });
  it("parses timecodes", () => {
    expect(parseSeconds("01:05")).toBe(65);
    expect(parseSeconds(12.5)).toBe(12.5);
    expect(formatTime(3725)).toBe("1:02:05");
  });
  it("keeps exact verdict keys", () => {
    expect(Object.keys(VERDICT_LABEL).sort()).toEqual(["no_violation", "violation"]);
  });
  it("rejects unsafe links", () => {
    expect(isSafeHttpUrl("javascript:alert(1)")).toBe(false);
    expect(isSafeHttpUrl("https://adilet.zan.kz")).toBe(true);
  });
});
