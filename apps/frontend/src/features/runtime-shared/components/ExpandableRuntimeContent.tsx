export function ExpandableRuntimeContent({
  content,
  defaultOpen = false,
  label,
}: {
  content: string;
  defaultOpen?: boolean;
  label: string;
}) {
  const shouldCollapse = runPayloadShouldCollapse(content);
  if (!shouldCollapse) return <pre>{content}</pre>;
  return (
    <details className="run-expandable-content" open={defaultOpen}>
      <summary>
        <span>{label}</span>
        <em>{runPayloadSummary(content)}</em>
      </summary>
      <pre>{content}</pre>
    </details>
  );
}

function payloadLineCount(value: string): number {
  if (!value) return 0;
  return value.split(/\r?\n/).length;
}

function runPayloadShouldCollapse(value: string): boolean {
  return value.length > 700 || payloadLineCount(value) > 10;
}

function runPayloadSummary(value: string): string {
  const lines = payloadLineCount(value);
  const units = [`${lines} 行`, `${value.length} 字符`];
  return units.join(' · ');
}
