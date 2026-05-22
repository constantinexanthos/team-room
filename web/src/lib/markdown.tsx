import { Fragment, type ReactNode } from 'react';
import { lexer, type Token, type Tokens } from 'marked';

/**
 * Render a markdown string as React elements.
 *
 * We avoid React's raw-HTML injection prop (the repo's pre-commit hook blocks
 * any usage of it). Instead we lex with `marked` and walk the AST, emitting
 * plain JSX. No sanitizer needed — every string lands inside a React text
 * node, which means React escapes it for us.
 *
 * Heuristics we keep light:
 *   - `code` and `pre` use the mono font; everything else uses sans.
 *   - A line that is exactly `# CONVERGED` (the orchestration marker) is
 *     emitted as a styled badge so it pops out of long transcripts.
 *   - Links open in a new tab with `rel="noopener noreferrer"`.
 */
export function Markdown({ source }: { source: string }) {
  // Short-circuit the convergence marker so its visual treatment doesn't
  // depend on how marked tokenizes `# CONVERGED`.
  if (source.trim() === '# CONVERGED') {
    return <ConvergedBadge />;
  }

  let tokens: Token[];
  try {
    tokens = lexer(source);
  } catch {
    // Lexer failure (shouldn't happen on real input) → fall back to raw text
    // so we never lose content.
    return <p className="whitespace-pre-wrap break-words">{source}</p>;
  }
  return <>{renderTokens(tokens)}</>;
}

function renderTokens(tokens: Token[]): ReactNode[] {
  return tokens.map((token, i) => (
    <Fragment key={i}>{renderToken(token)}</Fragment>
  ));
}

function renderToken(token: Token): ReactNode {
  switch (token.type) {
    case 'space':
      return null;

    case 'heading': {
      const t = token as Tokens.Heading;
      // The agents use `# CONVERGED` as a section marker; treat any heading
      // whose plain text is exactly "CONVERGED" as a badge.
      if (t.text.trim() === 'CONVERGED') {
        return <ConvergedBadge />;
      }
      const sizes: Record<number, string> = {
        1: 'text-base font-semibold mt-3 mb-1.5',
        2: 'text-[15px] font-semibold mt-3 mb-1.5',
        3: 'text-sm font-semibold mt-2.5 mb-1',
        4: 'text-sm font-semibold mt-2 mb-1 text-[var(--color-muted)]',
        5: 'text-xs font-semibold uppercase tracking-[0.1em] mt-2 mb-1 text-[var(--color-muted)]',
        6: 'text-xs font-semibold uppercase tracking-[0.1em] mt-2 mb-1 text-[var(--color-muted)]',
      };
      const cls = sizes[t.depth] ?? sizes[3];
      const children = renderInline(t.tokens);
      switch (t.depth) {
        case 1:
          return <h1 className={cls}>{children}</h1>;
        case 2:
          return <h2 className={cls}>{children}</h2>;
        case 3:
          return <h3 className={cls}>{children}</h3>;
        case 4:
          return <h4 className={cls}>{children}</h4>;
        case 5:
          return <h5 className={cls}>{children}</h5>;
        default:
          return <h6 className={cls}>{children}</h6>;
      }
    }

    case 'paragraph': {
      const t = token as Tokens.Paragraph;
      return (
        <p className="my-1.5 whitespace-pre-wrap break-words">
          {renderInline(t.tokens)}
        </p>
      );
    }

    case 'blockquote': {
      const t = token as Tokens.Blockquote;
      return (
        <blockquote className="my-2 border-l-2 border-[var(--color-border-strong)] pl-3 text-[var(--color-muted)]">
          {renderTokens(t.tokens)}
        </blockquote>
      );
    }

    case 'code': {
      const t = token as Tokens.Code;
      return (
        <pre className="my-2 overflow-x-auto rounded-md border border-[var(--color-border)] bg-[var(--color-bg)] p-2.5 font-mono text-[12.5px] leading-relaxed text-[var(--color-text)]">
          <code>{t.text}</code>
        </pre>
      );
    }

    case 'hr':
      return <hr className="my-3 border-0 border-t border-[var(--color-border)]" />;

    case 'list': {
      const t = token as Tokens.List;
      const items = t.items.map((item, i) => (
        <li key={i} className="my-0.5">
          {renderTokens(item.tokens)}
        </li>
      ));
      if (t.ordered) {
        const startAttr = typeof t.start === 'number' ? t.start : undefined;
        return (
          <ol
            className="my-1.5 ml-5 list-decimal space-y-0.5"
            start={startAttr}
          >
            {items}
          </ol>
        );
      }
      return (
        <ul className="my-1.5 ml-5 list-disc space-y-0.5">{items}</ul>
      );
    }

    case 'html': {
      // Don't render raw HTML — emit it as text so the user can see it
      // and we never leak script tags.
      const t = token as Tokens.HTML;
      return (
        <pre className="my-2 overflow-x-auto whitespace-pre-wrap break-words font-mono text-[12.5px] text-[var(--color-muted)]">
          {t.text}
        </pre>
      );
    }

    case 'table': {
      const t = token as Tokens.Table;
      return (
        <div className="my-2 overflow-x-auto">
          <table className="border-collapse text-[13px]">
            <thead>
              <tr>
                {t.header.map((cell, i) => (
                  <th
                    key={i}
                    className="border border-[var(--color-border)] px-2 py-1 text-left font-semibold"
                    style={cell.align ? { textAlign: cell.align } : undefined}
                  >
                    {renderInline(cell.tokens)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {t.rows.map((row, ri) => (
                <tr key={ri}>
                  {row.map((cell, ci) => (
                    <td
                      key={ci}
                      className="border border-[var(--color-border)] px-2 py-1"
                      style={
                        cell.align ? { textAlign: cell.align } : undefined
                      }
                    >
                      {renderInline(cell.tokens)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    }

    default:
      // Inline tokens that escape from block-level contexts (rare) fall through
      // here. Render them via the inline path so we don't drop them.
      return renderInlineToken(token);
  }
}

function renderInline(tokens: Token[] | undefined): ReactNode[] {
  if (!tokens) return [];
  return tokens.map((token, i) => (
    <Fragment key={i}>{renderInlineToken(token)}</Fragment>
  ));
}

function renderInlineToken(token: Token): ReactNode {
  switch (token.type) {
    case 'text': {
      const t = token as Tokens.Text;
      if (t.tokens && t.tokens.length > 0) {
        return <>{renderInline(t.tokens)}</>;
      }
      return t.text;
    }
    case 'escape':
      return (token as Tokens.Escape).text;
    case 'strong':
      return <strong className="font-semibold">{renderInline((token as Tokens.Strong).tokens)}</strong>;
    case 'em':
      return <em className="italic">{renderInline((token as Tokens.Em).tokens)}</em>;
    case 'del':
      return <del>{renderInline((token as Tokens.Del).tokens)}</del>;
    case 'codespan': {
      const t = token as Tokens.Codespan;
      return (
        <code className="rounded bg-[var(--color-bg)] px-1 py-px font-mono text-[12.5px] text-[var(--color-text)]">
          {decodeEntities(t.text)}
        </code>
      );
    }
    case 'br':
      return <br />;
    case 'link': {
      const t = token as Tokens.Link;
      const safe = isSafeUrl(t.href) ? t.href : '#';
      return (
        <a
          href={safe}
          title={t.title ?? undefined}
          target="_blank"
          rel="noopener noreferrer"
          className="text-[var(--color-costa)] underline-offset-2 hover:underline"
        >
          {renderInline(t.tokens)}
        </a>
      );
    }
    case 'image': {
      const t = token as Tokens.Image;
      const safe = isSafeUrl(t.href) ? t.href : '';
      // Render images as a labelled link rather than a real <img> — avoids
      // surprise network requests when we're displaying agent output.
      return (
        <a
          href={safe || '#'}
          target="_blank"
          rel="noopener noreferrer"
          className="text-[var(--color-costa)] underline-offset-2 hover:underline"
        >
          [image: {t.text || safe}]
        </a>
      );
    }
    case 'html': {
      const t = token as Tokens.Tag;
      return t.text;
    }
    default:
      // Unknown inline token — emit its raw markdown.
      return ('raw' in token && typeof (token as { raw?: unknown }).raw === 'string')
        ? (token as { raw: string }).raw
        : '';
  }
}

function isSafeUrl(href: string): boolean {
  if (!href) return false;
  const trimmed = href.trim().toLowerCase();
  if (trimmed.startsWith('javascript:') || trimmed.startsWith('data:') || trimmed.startsWith('vbscript:')) {
    return false;
  }
  return true;
}

function decodeEntities(s: string): string {
  // marked encodes a few HTML entities in `codespan.text`. Reverse those so
  // the raw character shows in the rendered <code>.
  return s
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'");
}

function ConvergedBadge() {
  return (
    <div className="my-2 inline-flex items-center gap-2 rounded-full border border-[var(--color-codex)]/40 bg-[var(--color-codex)]/10 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.12em] text-[var(--color-codex)]">
      <span className="inline-block size-1.5 rounded-full bg-[var(--color-codex)]" aria-hidden="true" />
      Converged
    </div>
  );
}
