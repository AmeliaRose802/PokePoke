import { useState } from "react";

import type { CompletedItem, ModelHistoryEntry } from "../types";
import { getItemStats } from "../utils/stats";

type CopyStatus = "idle" | "success" | "error";

export function useCopyCompletedItems() {
  const [copyStatus, setCopyStatus] = useState<CopyStatus>("idle");

  const copyCompletedItems = async (completedItems: CompletedItem[], modelHistory: ModelHistoryEntry[]) => {
    try {
      if (!navigator.clipboard) {
        throw new Error("Clipboard API not available");
      }

      if (completedItems.length === 0) {
        return;
      }

      // Format completed items for copying
      const formattedItems = completedItems
        .map((item, index) => {
          const itemStats = getItemStats(item.id, modelHistory);
          const gateStatus =
            itemStats?.gate_passed === true
              ? "Passed gate"
              : itemStats?.gate_passed === false
                ? "Failed gate"
                : "Pending";

          let line = `${index + 1}. ${item.id}`;
          if (item.title) {
            line += ` - ${item.title}`;
          }
          line += ` (${gateStatus})`;

          if (itemStats?.model) {
            line += ` [${itemStats.model}]`;
          }

          return line;
        })
        .join("\n");

      const header = `Completed this session (${completedItems.length} items):\n`;
      const fullText = header + formattedItems;

      await navigator.clipboard.writeText(fullText);
      setCopyStatus("success");
      setTimeout(() => setCopyStatus("idle"), 2000);
    } catch (error) {
      console.error("Failed to copy to clipboard:", error);
      setCopyStatus("error");
      setTimeout(() => setCopyStatus("idle"), 2000);
    }
  };

  return { copyStatus, copyCompletedItems };
}
