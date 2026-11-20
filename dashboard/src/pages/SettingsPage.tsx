import { useEffect, useState } from "react";
import { api, Settings, TestResult } from "../api";
import { Banner, PageHeader, Switch } from "../components/ui";

interface Form {
  budget: string;
  keep: string;
  drop: string;
  fallback: boolean;
  jevKey: string;
  cfAccount: string;
  cfToken: string;
}

const toForm = (s: Settings): Form => ({
  budget: String(s.budget),
  keep: s.keep_threshold.toFixed(2),
  drop: s.drop_threshold.toFixed(2),
  fallback: s.fallback_enabled,
  jevKey: "",
  cfAccount: s.cf_account_id,
  cfToken: "",
});

function validate(f: Form) {
  const errors: Partial<Record<"budget" | "keep" | "drop", string>> = {};
  const budget = Number(f.budget);
  const keep = Number(f.keep);
  const drop = Number(f.drop);
  if (!Number.isInteger(budget) || budget <= 0) errors.budget = "Enter a whole number of tokens above 0.";
  if (f.keep === "" || isNaN(keep) || keep < 0 || keep > 1) errors.keep = "Enter a number from 0 to 1.";
  if (f.drop === "" || isNaN(drop) || drop < 0 || drop > 1) errors.drop = "Enter a number from 0 to 1.";
  if (!errors.keep && !errors.drop && keep <= drop) errors.keep = "Keep threshold must be higher than drop threshold.";
  return errors;
}

function TestStatus({ result }: { result: TestResult | "testing" | null }) {
  if (!result) return null;
  if (result === "testing") return <span className="hint">Testing…</span>;
  return result.ok ? (
    <span className="ok" role="status">✓ Connected</span>
  ) : (
    <span className="error" role="status">✗ {result.message}</span>
  );
}

export default function SettingsPage() {
  const [saved, setSaved] = useState<Settings | null>(null);
  const [f, setF] = useState<Form | null>(null);
  const [showJev, setShowJev] = useState(false);
  const [showCf, setShowCf] = useState(false);
  const [jevTest, setJevTest] = useState<TestResult | "testing" | null>(null);
  const [cfTest, setCfTest] = useState<TestResult | "testing" | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .settings()
      .then((s) => {
        setSaved(s);
        setF(toForm(s));
      })
      .catch((e) => setError(String(e.message ?? e)));
  }, []);

  if (!f || !saved) return <PageHeader title="Settings" sub={error ?? "Loading…"} />;

  const errors = validate(f);
  const valid = Object.keys(errors).length === 0;
  const set = (patch: Partial<Form>) => {
    setF({ ...f, ...patch });
    setNotice(null);
  };

  async function save() {
    if (!f || !valid) return;
    setError(null);
    try {
      const body: Record<string, unknown> = {
        budget: Number(f.budget),
        keep_threshold: Number(f.keep),
        drop_threshold: Number(f.drop),
        preset: "custom",
        fallback_enabled: f.fallback,
        never_drop_errors: true,
        cf_account_id: f.cfAccount,
      };
      if (f.jevKey) body.jev_api_key = f.jevKey;
      if (f.cfToken) body.cf_api_token = f.cfToken;
      const s = await api.saveSettings(body);
      setSaved(s);
      setF(toForm(s));
      setNotice("Settings saved.");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function reset() {
    const s = await api.resetSettings();
    setSaved(s);
    setF(toForm(s));
    setNotice("Thresholds, budget and toggles reset to defaults. Saved keys were kept.");
  }

  return (
    <>
      <PageHeader
        title="Settings"
        sub={`Judge: ${saved.judge} · Summarizer: ${saved.summarizer}. Keys are encrypted on this machine and never shown in full.`}
        actions={
          <>
            <button className="btn" onClick={reset}>
              Reset to defaults
            </button>
            <button className="btn btn-primary" onClick={save} disabled={!valid}>
              Save changes
            </button>
          </>
        }
      />
      {error && (
        <Banner kind="error" label="Error" actions={[{ label: "Dismiss", onClick: () => setError(null) }]}>
          {error}
        </Banner>
      )}
      {notice && (
        <Banner kind="info" label="Saved" actions={[{ label: "Dismiss", onClick: () => setNotice(null) }]}>
          {notice}
        </Banner>
      )}

      <div className="settings">
        <div className="col">
        <section className="card card-pad stack" aria-labelledby="jev-h">
          <h2 id="jev-h">Jev (TypeSafe AI)</h2>
          <div className="field">
            <label htmlFor="jev-key">API key</label>
            <div className="key-row">
              <input
                id="jev-key"
                className="input mono"
                type={showJev ? "text" : "password"}
                autoComplete="off"
                placeholder={saved.jev_api_key_masked ?? "Paste your Jev API key"}
                value={f.jevKey}
                onChange={(e) => set({ jevKey: e.target.value })}
              />
              <button className="btn" type="button" onClick={() => setShowJev(!showJev)} aria-pressed={showJev}>
                {showJev ? "Hide" : "Show"}
              </button>
              <button
                className="btn"
                type="button"
                onClick={async () => {
                  setJevTest("testing");
                  setJevTest(await api.testJev(f.jevKey));
                }}
              >
                Test connection
              </button>
            </div>
            <span className="hint">
              {saved.jev_api_key_set ? "A key is saved. Type a new one to replace it." : "No key saved: the mock judge is used."}
            </span>
            <TestStatus result={jevTest} />
          </div>
        </section>

        <section className="card card-pad stack" aria-labelledby="cf-h">
          <h2 id="cf-h">Cloudflare Workers AI</h2>
          <div className="field">
            <label htmlFor="cf-account">Account ID</label>
            <input
              id="cf-account"
              className="input mono"
              autoComplete="off"
              placeholder="Your Cloudflare account ID"
              value={f.cfAccount}
              onChange={(e) => set({ cfAccount: e.target.value })}
            />
          </div>
          <div className="field">
            <label htmlFor="cf-token">API token</label>
            <div className="key-row">
              <input
                id="cf-token"
                className="input mono"
                type={showCf ? "text" : "password"}
                autoComplete="off"
                placeholder={saved.cf_api_token_masked ?? "Paste your Workers AI API token"}
                value={f.cfToken}
                onChange={(e) => set({ cfToken: e.target.value })}
              />
              <button className="btn" type="button" onClick={() => setShowCf(!showCf)} aria-pressed={showCf}>
                {showCf ? "Hide" : "Show"}
              </button>
              <button
                className="btn"
                type="button"
                onClick={async () => {
                  setCfTest("testing");
                  setCfTest(await api.testCloudflare(f.cfAccount, f.cfToken));
                }}
              >
                Test connection
              </button>
            </div>
            <TestStatus result={cfTest} />
          </div>
        </section>

        </div>
        <section className="card card-pad stack" aria-labelledby="comp-h">
          <h2 id="comp-h">Compaction</h2>
          <div className="field">
            <label htmlFor="budget">Token budget</label>
            <input
              id="budget"
              className={`input ${errors.budget ? "invalid" : ""}`}
              inputMode="numeric"
              value={f.budget}
              aria-invalid={!!errors.budget}
              onChange={(e) => set({ budget: e.target.value })}
            />
            {errors.budget ? (
              <span className="error">{errors.budget}</span>
            ) : (
              <span className="hint">Compaction starts when a session passes this many tokens.</span>
            )}
          </div>
          <div className="grid2">
            <div className="field">
              <label htmlFor="keep-t">Keep threshold</label>
              <input
                id="keep-t"
                className={`input ${errors.keep ? "invalid" : ""}`}
                inputMode="decimal"
                value={f.keep}
                aria-invalid={!!errors.keep}
                aria-describedby="keep-err"
                onChange={(e) => set({ keep: e.target.value })}
              />
              {errors.keep ? (
                <span className="error" id="keep-err" role="alert">
                  {errors.keep}
                </span>
              ) : (
                <span className="hint">Kept verbatim at or above this score.</span>
              )}
            </div>
            <div className="field">
              <label htmlFor="drop-t">Drop threshold</label>
              <input
                id="drop-t"
                className={`input ${errors.drop ? "invalid" : ""}`}
                inputMode="decimal"
                value={f.drop}
                aria-invalid={!!errors.drop}
                onChange={(e) => set({ drop: e.target.value })}
              />
              {errors.drop ? <span className="error">{errors.drop}</span> : <span className="hint">Dropped below this score.</span>}
            </div>
          </div>
          <Switch label="Fall back to the plain summary if Jev fails" checked={f.fallback} onChange={(v) => set({ fallback: v })} />
          <Switch label="Never drop error output (always on)" checked locked />
        </section>
      </div>
    </>
  );
}
