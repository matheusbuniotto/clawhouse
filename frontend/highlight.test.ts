import { expect, test } from "vitest";

import { highlight, normalizeLanguage } from "./highlight";

test("normalizes common language aliases", () => {
  expect(normalizeLanguage("py")).toBe("python");
  expect(normalizeLanguage("Bash")).toBe("shell");
  expect(normalizeLanguage("JSON")).toBe("json");
  expect(normalizeLanguage("unknown")).toBe("unknown");
});

test("tokenizes a JSON snippet exactly", () => {
  expect(highlight('{"a": 1}', "json")).toEqual([
    { text: "{", kind: "plain" },
    { text: '"a"', kind: "key" },
    { text: ": ", kind: "plain" },
    { text: "1", kind: "number" },
    { text: "}", kind: "plain" },
  ]);
});

test("tokenizes Python numbers and comments", () => {
  expect(highlight("x = 1  # n", "python")).toEqual([
    { text: "x = ", kind: "plain" },
    { text: "1", kind: "number" },
    { text: "  ", kind: "plain" },
    { text: "# n", kind: "comment" },
  ]);
});

test("tokenizes shell keywords and variables", () => {
  expect(highlight("echo $HOME", "shell")).toEqual([
    { text: "echo", kind: "keyword" },
    { text: " ", kind: "plain" },
    { text: "$HOME", kind: "variable" },
  ]);
});

test("tokenizes SQL keywords", () => {
  const kinds = highlight("SELECT id FROM t", "sql")
    .filter((token) => token.kind !== "plain")
    .map((token) => `${token.kind}:${token.text}`);
  expect(kinds).toEqual(["keyword:SELECT", "keyword:FROM"]);
});

test("falls back to plain text for unknown languages", () => {
  expect(highlight("anything", "brainfuck")).toEqual([{ text: "anything", kind: "plain" }]);
});
