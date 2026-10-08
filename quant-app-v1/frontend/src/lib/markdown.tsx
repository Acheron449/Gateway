import { useState, type ReactNode } from "react";

/**
 * Lightweight, dependency-free Markdown renderer for AI chat output.
 *
 * Supports: headings, bold/italic/strikethrough, inline code, fenced code
 * blocks with a copy button, GFM tables (wrapped so wide tables scroll
 * horizontally inside the chat), unordered/ordered lists, blockquotes,
 * horizontal rules, and links. Everything else degrades to plain text.
 */

// ---------------------------------------------------------------------------
// Inline rendering
// ---------------------------------------------------------------------------

const INLINE_RE =
  /(`[^`\n]+`)|(\*\*[^*\n]+\*\*)|(__[^_\n]+__)|(~~[^~\n]+~~)|(\*[^*\n]+\*)|(_[^_\n]+_)|(\[[^\]\n]+\]\([^)\s]+\))/;

function renderInline(text: string, keyPrefix = "i"): ReactNode[] {
  const nodes: ReactNode[] = [];
  let rest = text;
  let index = 0;
  let guard = 0;

  while (rest && guard++ < 5000) {
    const match = INLINE_RE.exec(rest);
    if (!match || match.index === undefined || match.index === -1) {
      nodes.push(rest);
      break;
    }
    if (match.index > 0) nodes.push(rest.slice(0, match.index));
    const token = match[0];
    const key = `${keyPrefix}-${index++}`;

    if (token.startsWith("`")) {
      nodes.push(
        <code key={key} className="md-inline-code">
          {token.slice(1, -1)}
        </code>,
      );
    } else if (token.startsWith("**") || token.startsWith("__")) {
      nodes.push(<strong key={key}>{renderInline(token.slice(2, -2), key)}</strong>);
    } else if (token.startsWith("~~")) {
      nodes.push(<del key={key}>{renderInline(token.slice(2, -2), key)}</del>);
    } else if (token.startsWith("*") || token.startsWith("_")) {
      nodes.push(<em key={key}>{renderInline(token.slice(1, -1), key)}</em>);
    } else if (token.startsWith("[")) {
      const close = token.indexOf("](");
      const label = token.slice(1, close);
      const href = token.slice(close + 2, -1);
      const safe = /^(https?:|\/|#|mailto:)/i.test(href) ? href : "#";
      nodes.push(
        <a key={key} href={safe} target="_blank" rel="noreferrer noopener" className="md-link">
          {renderInline(label, key)}
        </a>,
      );
    } else {
      nodes.push(token);
    }
    rest = rest.slice(match.index + token.length);
  }
  if (rest) nodes.push(rest);
  return nodes;
}

// ---------------------------------------------------------------------------
// Code block with copy button
// ---------------------------------------------------------------------------

function CodeBlock({ code, lang }: { code: string; lang: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard unavailable */
    }
  };
  return (
    <div className="md-codeblock">
      <div className="md-codeblock-bar">
        <span className="md-codeblock-lang">{lang || "code"}</span>
        <button type="button" className="md-copy-btn" onClick={copy} aria-label="Copy code">
          {copied ? "Copied!" : "Copy"}
        </button>
      </div>
      <pre className="md-codeblock-pre">
        <code>{code}</code>
      </pre>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Table parsing
// ---------------------------------------------------------------------------

function splitRow(line: string): string[] {
  return line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((cell) => cell.trim());
}

function isTableSep(line: string): boolean {
  const t = line.trim();
  return /^\|?[\s:]*-{3,}[\s:]*(\|[\s:]*-{3,}[\s:]*)*\|?$/.test(t);
}

function Table({ rows }: { rows: string[][] }) {
  if (rows.length === 0) return null;
  const head = rows[0] ?? [];
  const body = rows.slice(1);
  return (
    <div className="md-table-wrap" role="region" aria-label="Table (scroll horizontally)">
      <table className="md-table">
        <thead>
          <tr>
            {head.map((cell, i) => (
              <th key={i}>{renderInline(cell, `th${i}`)}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {body.map((row, ri) => (
            <tr key={ri}>
              {row.map((cell, ci) => (
                <td key={ci}>{renderInline(cell, `td${ri}-${ci}`)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Block rendering
// ---------------------------------------------------------------------------

const RE_HEAD = /^(#{1,6})\s+(.*)$/;
const RE_FENCE = /^\s*```(\w*)/;
const RE_CLOSE_FENCE = /^\s*```/;
const RE_UL = /^\s*[-*+]\s+/;
const RE_OL = /^\s*\d+\.\s+/;
const RE_QUOTE = /^\s*>\s?/;
const RE_HR = /^\s*([-*_])\1{2,}\s*$/;

const HEADINGS = ["h1", "h2", "h3", "h4", "h5", "h6"] as const;
type HeadingTag = (typeof HEADINGS)[number];

export function Markdown({ content }: { content: string }) {
  const lines = (content || "").replace(/\r\n/g, "\n").split("\n");
  const blocks: ReactNode[] = [];
  const n = lines.length;
  let i = 0;
  let key = 0;

  const lineAt = (idx: number): string => lines[idx] ?? "";

  while (i < n) {
    const line = lineAt(i);

    // Fenced code block
    const fence = RE_FENCE.exec(line);
    if (fence && line.trim().startsWith("```")) {
      const lang = fence[1] || "";
      i++;
      const buf: string[] = [];
      while (i < n && !RE_CLOSE_FENCE.test(lineAt(i))) {
        buf.push(lineAt(i));
        i++;
      }
      i++; // closing fence (or end)
      blocks.push(<CodeBlock key={`code${key++}`} code={buf.join("\n")} lang={lang} />);
      continue;
    }

    // Blank line
    if (!line.trim()) {
      i++;
      continue;
    }

    // Table: a pipe row followed by a separator row
    const next = i + 1 < n ? lineAt(i + 1) : "";
    if (line.includes("|") && next && isTableSep(next)) {
      const rows: string[][] = [splitRow(line)];
      i += 2;
      while (i < n && lineAt(i).includes("|") && lineAt(i).trim()) {
        rows.push(splitRow(lineAt(i)));
        i++;
      }
      blocks.push(<Table key={`tbl${key++}`} rows={rows} />);
      continue;
    }

    // Heading
    const heading = RE_HEAD.exec(line);
    if (heading) {
      const level = Math.min((heading[1] ?? "#").length, 6);
      const Tag: HeadingTag = HEADINGS[level - 1] ?? "h6";
      const cls = `md-heading md-h${level}`;
      const body = heading[2] ?? "";
      blocks.push(
        <Tag key={`h${key++}`} className={cls}>
          {renderInline(body, `h${key}`)}
        </Tag>,
      );
      i++;
      continue;
    }

    // Horizontal rule
    if (RE_HR.test(line)) {
      blocks.push(<hr key={`hr${key++}`} className="md-hr" />);
      i++;
      continue;
    }

    // Blockquote
    if (RE_QUOTE.test(line)) {
      const buf: string[] = [];
      while (i < n && RE_QUOTE.test(lineAt(i))) {
        buf.push(lineAt(i).replace(RE_QUOTE, ""));
        i++;
      }
      blocks.push(
        <blockquote key={`bq${key++}`} className="md-quote">
          {renderInline(buf.join(" "), `bq${key}`)}
        </blockquote>,
      );
      continue;
    }

    // Unordered list
    if (RE_UL.test(line)) {
      const items: ReactNode[] = [];
      while (i < n && RE_UL.test(lineAt(i))) {
        const text = lineAt(i).replace(RE_UL, "");
        items.push(<li key={`li${key++}`}>{renderInline(text, `li${key}`)}</li>);
        i++;
      }
      blocks.push(<ul key={`ul${key++}`}>{items}</ul>);
      continue;
    }

    // Ordered list
    if (RE_OL.test(line)) {
      const items: ReactNode[] = [];
      while (i < n && RE_OL.test(lineAt(i))) {
        const text = lineAt(i).replace(RE_OL, "");
        items.push(<li key={`li${key++}`}>{renderInline(text, `li${key}`)}</li>);
        i++;
      }
      blocks.push(<ol key={`ol${key++}`}>{items}</ol>);
      continue;
    }

    // Paragraph: gather consecutive plain lines
    const buf: string[] = [];
    while (i < n) {
      const cur = lineAt(i);
      if (
        !cur.trim() ||
        RE_CLOSE_FENCE.test(cur) ||
        RE_HEAD.test(cur) ||
        RE_UL.test(cur) ||
        RE_OL.test(cur) ||
        RE_QUOTE.test(cur) ||
        RE_HR.test(cur)
      ) {
        break;
      }
      const curNext = i + 1 < n ? lineAt(i + 1) : "";
      if (cur.includes("|") && curNext && isTableSep(curNext)) break;
      buf.push(cur);
      i++;
    }
    if (buf.length) {
      blocks.push(
        <p key={`p${key++}`} className="md-para">
          {renderInline(buf.join(" "), `p${key}`)}
        </p>,
      );
    } else {
      // Safety: avoid an infinite loop on an unmatched line.
      blocks.push(
        <p key={`p${key++}`} className="md-para">
          {renderInline(line, `p${key}`)}
        </p>,
      );
      i++;
    }
  }

  return <div className="md-body">{blocks}</div>;
}
