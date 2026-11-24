/**
 * An answer's content: markdown text with citation chips, the cited sources,
 * and the exact rows the stats queries returned.
 *
 * - Markdown (GFM, for the model's tables) through react-markdown, which
 *   never renders raw HTML and drops unsafe URLs (javascript: and the like).
 *   Answers include paraphrased Wikipedia text, so that matters.
 * - "[S3]" becomes a chip linking to source S3, once the backend has sent it
 *   as a citation; an id it never sent stays plain text.
 * - The stats rows (`table` events) are behind a "Show the data" disclosure:
 *   the model already writes its own table into the text, sometimes cut
 *   short, so these are the exact numbers without showing everything twice.
 */

import type { ReactNode } from "react";
import ReactMarkdown, { defaultUrlTransform, type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

import type { Source, Table } from "@/lib/chat";

const CITE = "cite:";
const MARKER = /\[(S\d+)\](?!\()/g;

/** "[S3]" → "[S3](cite:S3)" for known sources, so the link renderer makes a chip. */
export function linkCitations(text: string, known: ReadonlySet<string>): string {
  return text.replace(MARKER, (marker, id: string) =>
    known.has(id) ? `[${id}](${CITE}${id})` : marker,
  );
}

function urlTransform(url: string): string {
  return url.startsWith(CITE) ? url : defaultUrlTransform(url);
}

export function sourceNumber(id: string): string {
  return id.replace(/^S/, "");
}

export function sourceLabel(source: Source): string {
  return [source.title, source.section].filter(Boolean).join(" › ");
}

function CitationChip({ source }: { source: Source }) {
  return (
    <a
      href={source.url}
      target="_blank"
      rel="noopener noreferrer"
      title={sourceLabel(source)}
      aria-label={`Source ${sourceNumber(source.id)}: ${sourceLabel(source)}`}
      className="mx-0.5 inline-flex h-5 min-w-5 -translate-y-0.5 items-center justify-center rounded-full bg-raised px-1.5 align-middle text-[0.7rem] font-semibold text-accent-text no-underline hover:bg-accent hover:text-on-accent"
    >
      {sourceNumber(source.id)}
    </a>
  );
}

function markdownComponents(sources: ReadonlyMap<string, Source>): Components {
  return {
    a({ href, children }) {
      if (href?.startsWith(CITE)) {
        const source = sources.get(href.slice(CITE.length));
        return source ? <CitationChip source={source} /> : <>{children}</>;
      }
      if (!href) return <>{children}</>;
      return (
        <a
          href={href}
          target="_blank"
          rel="noopener noreferrer nofollow"
          className="text-accent-text underline underline-offset-2 hover:text-foreground"
        >
          {children}
        </a>
      );
    },
    p: ({ children }) => (
      <p className="my-2 leading-relaxed first:mt-0 last:mb-0">{children}</p>
    ),
    strong: ({ children }) => (
      <strong className="font-semibold text-foreground">{children}</strong>
    ),
    ul: ({ children }) => <ul className="my-2 list-disc space-y-1 pl-6">{children}</ul>,
    ol: ({ children }) => (
      <ol className="my-2 list-decimal space-y-1 pl-6">{children}</ol>
    ),
    li: ({ children }) => <li className="leading-relaxed">{children}</li>,
    h1: ({ children }) => <h3 className="mt-4 mb-2 text-lg font-bold">{children}</h3>,
    h2: ({ children }) => <h3 className="mt-4 mb-2 text-lg font-bold">{children}</h3>,
    h3: ({ children }) => <h4 className="mt-3 mb-1.5 font-semibold">{children}</h4>,
    h4: ({ children }) => <h4 className="mt-3 mb-1.5 font-semibold">{children}</h4>,
    blockquote: ({ children }) => (
      <blockquote className="my-2 border-l-2 border-accent pl-3 text-soft">
        {children}
      </blockquote>
    ),
    code: ({ children }) => (
      <code className="rounded bg-raised px-1 py-0.5 font-mono text-[0.85em]">
        {children}
      </code>
    ),
    pre: ({ children }) => (
      <pre className="my-2 overflow-x-auto rounded-lg bg-surface p-3 text-sm">
        {children}
      </pre>
    ),
    hr: () => <hr className="my-4 border-line" />,
    table: ({ children }) => <ScrollTable>{children}</ScrollTable>,
    th: ({ children, style }) => (
      <th
        style={style}
        className="border-b border-control bg-surface px-3 py-1.5 text-left text-xs font-semibold tracking-wide whitespace-nowrap text-soft uppercase"
      >
        {children}
      </th>
    ),
    td: ({ children, style }) => (
      <td style={style} className="border-b border-line px-3 py-1.5">
        {children}
      </td>
    ),
  };
}

function ScrollTable({ children }: { children: ReactNode }) {
  return (
    <div className="my-3 max-w-full overflow-x-auto rounded-lg border border-line">
      <table className="w-full border-collapse text-sm tabular-nums [&_tbody_tr:hover]:bg-surface [&_tbody_tr:last-child_td]:border-b-0">
        {children}
      </table>
    </div>
  );
}

/** "driver_name" → "Driver name". */
export function columnLabel(column: string): string {
  const words = column.replace(/_/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export function cellText(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number")
    return value.toLocaleString("en-GB", { maximumFractionDigits: 3 });
  if (typeof value === "boolean") return value ? "yes" : "no";
  return typeof value === "string" ? value : JSON.stringify(value);
}

function DataTable({ table }: { table: Table }) {
  return (
    <div>
      <ScrollTable>
        <thead>
          <tr>
            {table.columns.map((c) => (
              <th
                key={c}
                className="border-b border-control bg-surface px-3 py-1.5 text-left text-xs font-semibold tracking-wide whitespace-nowrap text-soft uppercase"
              >
                {columnLabel(c)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {table.rows.map((row, i) => (
            <tr key={i}>
              {table.columns.map((c, j) => (
                <td key={c} className="border-b border-line px-3 py-1.5">
                  {cellText(row[j])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </ScrollTable>
      {table.note && <p className="text-xs text-muted">{table.note}</p>}
    </div>
  );
}

function Sources({ sources }: { sources: Source[] }) {
  return (
    <section aria-label="Sources" className="mt-1">
      <h4 className="mb-1.5 text-xs font-semibold tracking-wider text-muted uppercase">
        Sources
      </h4>
      <ol className="flex flex-col gap-1 text-sm">
        {sources.map((s) => (
          <li key={s.id} className="flex items-baseline gap-2">
            <span className="inline-flex h-5 min-w-5 shrink-0 items-center justify-center rounded-full bg-raised px-1.5 text-[0.7rem] font-semibold text-accent-text">
              {sourceNumber(s.id)}
            </span>
            <a
              href={s.url}
              target="_blank"
              rel="noopener noreferrer"
              className="min-w-0 break-words text-soft hover:text-foreground hover:underline"
            >
              {s.title}
              {s.section && <span className="text-muted"> › {s.section}</span>}
            </a>
          </li>
        ))}
      </ol>
      <p className="mt-1.5 text-[0.7rem] text-muted">
        Text from Wikipedia, licensed under CC BY-SA 4.0.
      </p>
    </section>
  );
}

interface AnswerContentProps {
  text: string;
  citations: Source[];
  tables: Table[];
  /** Hide the sources and data until the answer is complete. */
  complete: boolean;
}

export function AnswerContent({ text, citations, tables, complete }: AnswerContentProps) {
  const sources = new Map(citations.map((s) => [s.id, s]));
  const rows = tables.reduce((n, t) => n + t.rows.length, 0);
  return (
    <>
      {text && (
        <div className="min-w-0 break-words text-foreground" data-testid="answer-text">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            urlTransform={urlTransform}
            components={markdownComponents(sources)}
          >
            {linkCitations(text, new Set(sources.keys()))}
          </ReactMarkdown>
        </div>
      )}
      {complete && citations.length > 0 && <Sources sources={citations} />}
      {complete && rows > 0 && (
        <details className="group text-sm">
          <summary className="cursor-pointer select-none text-xs text-muted hover:text-foreground">
            Show the data ({rows} {rows === 1 ? "row" : "rows"} from the stats database)
          </summary>
          <div className="mt-1 flex flex-col gap-2">
            {tables.map((t, i) => (
              <DataTable key={i} table={t} />
            ))}
          </div>
        </details>
      )}
    </>
  );
}
