// One quiet trace line for a run of tool calls ("Read 2 files, searched code"),
// opening to its steps. A step waiting for the owner shows its card right here.

import { ChevronDown, ChevronRight } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";

import type { Activity as ActivityItem } from "../../lib/activity.ts";
import type { ToolBlock } from "../../lib/transcript.ts";
import { ApprovalCard, type ApproveFn } from "./ApprovalCard.tsx";
import { StepIcon } from "./icons.tsx";
import { Step } from "./Steps.tsx";

export function Activity({
  item,
  workspace,
  running,
  onApprove,
  renderChildren,
}: {
  item: ActivityItem;
  workspace: string;
  running: boolean;
  onApprove: ApproveFn;
  renderChildren: (step: ToolBlock) => ReactNode;
}) {
  const [open, setOpen] = useState(item.tone === "error");
  useEffect(() => {
    if (item.tone === "error") setOpen(true);
  }, [item.tone]);
  const pending = item.steps.filter((s) => s.approval?.status === "pending");
  const expandable = item.steps.some((s) => s.result || s.children?.blocks.length || s.args);
  return (
    <div className={`activity ${item.tone}`}>
      <button className="activityLine" aria-expanded={open} aria-disabled={!expandable} onClick={() => expandable && setOpen((v) => !v)}>
        <StepIcon kind={item.icon} />
        <span className="label">{item.label}</span>
        {expandable ? open ? <ChevronDown size={13} className="faint" /> : <ChevronRight size={13} className="faint" /> : null}
      </button>
      {open ? (
        <div className="activityDetail">
          {item.steps.map((step) => (
            <Step key={step.key} step={step} workspace={workspace} running={running} renderChildren={renderChildren} />
          ))}
        </div>
      ) : null}
      {pending.map((step) => (
        <ApprovalCard key={step.approval!.request.id} approval={step.approval!} workspace={workspace} onApprove={onApprove} />
      ))}
    </div>
  );
}
