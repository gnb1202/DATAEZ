import type { AgentStep } from "../lib/api";

// Only application-generated review routes become links. Tool text and file
// names remain escaped React text; arbitrary URLs/HTML are never interpreted.
const uuid = "[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}";
const reviewPath = new RegExp(`^/dashboard\\?project=${uuid}&section=tables&source=${uuid}(?:&batch=${uuid})?$`);
const cashPath = new RegExp(`^/dashboard\\?project=${uuid}&section=tables&cash_draft=${uuid}$`);
const reviewTools = new Set(["list_ledger_sources", "list_import_history", "inspect_import_review", "draft_cash_entry", "get_cash_entry"]);

export function ImportReviewLinks({ steps }: { steps?: AgentStep[] | null }) {
  const links = new Map<string, string>();
  // The most recently inspected upload takes priority over lookup lists.
  for (const step of [...(steps || [])].reverse()) {
    if (!reviewTools.has(step.tool_name || "") || step.tool_output?.error) continue;
    const output = step.tool_output;
    if (!output) continue;
    const items = output.review_url ? [{ ...output, filename: (output.batch as { filename?: string } | undefined)?.filename }]
      : Array.isArray(output.batches) ? output.batches : Array.isArray(output.sources) ? output.sources : [];
    for (const item of items) {
      if (!item || typeof item !== "object") continue;
      const { review_url: href, filename, name } = item as Record<string, unknown>;
      if (typeof href === "string" && (reviewPath.test(href) || cashPath.test(href)) && !links.has(href)) {
        links.set(href, typeof filename === "string" ? filename : typeof name === "string" ? name : cashPath.test(href) ? "현금 입력" : "출처");
      }
    }
  }
  if (!links.size) return null;
  return <div aria-label="출처 검토 화면" className="flex flex-wrap gap-2">
    {[...links].slice(0, 5).map(([href, label]) => <a key={href} href={href}
      className="rounded-lg border border-border bg-secondary px-3 py-2 text-sm underline hover:border-accent">
      {label} 검토하기
    </a>)}
  </div>;
}
