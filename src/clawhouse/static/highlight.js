/**
 * Dependency-free syntax highlighting for the transcript's fenced code blocks.
 * Four common languages plus a plain fallback; every token is rendered through
 * `tokens.css` colour tokens, never inline styles.
 */
const JSON_RULES = [
    { kind: "key", pattern: /"(?:\\.|[^"\\])*"(?=\s*:)/y },
    { kind: "string", pattern: /"(?:\\.|[^"\\])*"/y },
    { kind: "literal", pattern: /\b(?:true|false|null)\b/y },
    { kind: "number", pattern: /-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?/y },
];
const PYTHON_RULES = [
    { kind: "comment", pattern: /#[^\n]*/y },
    { kind: "string", pattern: /"""[\s\S]*?"""|'''[\s\S]*?'''|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'/y },
    {
        kind: "keyword",
        pattern: /\b(?:def|class|return|if|elif|else|for|while|in|not|and|or|is|None|True|False|import|from|as|with|try|except|finally|raise|yield|lambda|pass|break|continue|global|nonlocal|assert|del|await|async)\b/y,
    },
    { kind: "number", pattern: /\b\d+(?:\.\d+)?\b/y },
];
const SHELL_RULES = [
    { kind: "comment", pattern: /#[^\n]*/y },
    { kind: "string", pattern: /"(?:\\.|[^"\\])*"|'[^']*'/y },
    { kind: "variable", pattern: /\$\{[^}]*\}|\$[A-Za-z_][A-Za-z0-9_]*/y },
    {
        kind: "keyword",
        pattern: /\b(?:if|then|else|elif|fi|for|while|until|do|done|case|esac|function|in|export|local|return|source|set|unset|echo|exit)\b/y,
    },
];
const SQL_RULES = [
    { kind: "comment", pattern: /--[^\n]*/y },
    { kind: "string", pattern: /'(?:''|[^'])*'/y },
    {
        kind: "keyword",
        pattern: /\b(?:SELECT|FROM|WHERE|INSERT|INTO|VALUES|UPDATE|SET|DELETE|CREATE|TABLE|VIEW|INDEX|JOIN|LEFT|RIGHT|INNER|OUTER|FULL|ON|GROUP|BY|ORDER|HAVING|LIMIT|OFFSET|AS|AND|OR|NOT|NULL|IS|IN|DISTINCT|COUNT|SUM|AVG|MIN|MAX|CASE|WHEN|THEN|ELSE|END|UNION|ALL|WITH|ASC|DESC|PRIMARY|KEY|FOREIGN|REFERENCES|ALTER|DROP|ADD|COLUMN)\b/iy,
    },
];
const LANGUAGES = {
    json: JSON_RULES,
    python: PYTHON_RULES,
    shell: SHELL_RULES,
    sql: SQL_RULES,
};
export function normalizeLanguage(language) {
    const value = language.trim().toLowerCase();
    if (value === "py")
        return "python";
    if (value === "sh" || value === "bash" || value === "zsh")
        return "shell";
    return value;
}
export function highlight(code, language) {
    const rules = LANGUAGES[normalizeLanguage(language)];
    if (!rules)
        return [{ text: code, kind: "plain" }];
    return scan(code, rules);
}
function scan(code, rules) {
    const tokens = [];
    let plain = "";
    let index = 0;
    while (index < code.length) {
        let kind = null;
        let text = "";
        for (const rule of rules) {
            rule.pattern.lastIndex = index;
            const match = rule.pattern.exec(code);
            if (match) {
                kind = rule.kind;
                text = match[0];
                break;
            }
        }
        if (kind === null) {
            plain += code[index];
            index += 1;
            continue;
        }
        if (plain) {
            tokens.push({ text: plain, kind: "plain" });
            plain = "";
        }
        tokens.push({ text, kind });
        index += text.length;
    }
    if (plain)
        tokens.push({ text: plain, kind: "plain" });
    return tokens;
}
