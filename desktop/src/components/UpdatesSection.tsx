/**
 * Updates section for the Settings page.
 * Checks GitHub Releases for newer PokePoke versions.
 */

import { useCallback, useState } from "react";

import type { UpdateCheckResult } from "../types";

interface Props {
  checkForUpdates: () => Promise<UpdateCheckResult | null>;
}

export function UpdatesSection({ checkForUpdates }: Props) {
  const [checking, setChecking] = useState(false);
  const [result, setResult] = useState<UpdateCheckResult | null>(null);

  const handleCheck = useCallback(async () => {
    setChecking(true);
    const res = await checkForUpdates();
    setResult(res);
    setChecking(false);
  }, [checkForUpdates]);

  return (
    <div className="settings-section">
      <h3 className="settings-section-title">🔄 Updates</h3>
      <div className="settings-field">
        <button
          className="prompt-btn save"
          onClick={handleCheck}
          disabled={checking}
        >
          {checking ? "Checking…" : "Check for Updates"}
        </button>
        {result && (
          <div className="update-result">
            <div className="settings-hint">
              Current version: <strong>{result.current_version}</strong>
            </div>
            {result.error ? (
              <div className="settings-warning">⚠️ {result.error}</div>
            ) : result.update_available ? (
              <div className="update-available">
                🆕 Update available: <strong>v{result.latest_version}</strong>{" "}
                <a
                  href={result.download_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="update-download-link"
                >
                  Download
                </a>
              </div>
            ) : (
              <div className="settings-hint">
                ✅ PokePoke is up to date (v{result.latest_version ?? result.current_version})
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
