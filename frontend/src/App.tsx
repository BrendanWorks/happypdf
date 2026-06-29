import { useState, useEffect, useRef } from 'react';
import {
  FileText,
  Upload,
  CheckCircle,
  AlertTriangle,
  ChevronRight,
  Github,
  Zap,
  Eye,
  Code2,
  BarChart3,
  ShieldCheck,
  RefreshCw,
  ArrowRight,
  ExternalLink,
  X,
  ChevronDown,
  Layers,
  Globe,
  Key,
  Server,
  Cpu,
  Users,
  Sparkles,
  GitBranch,
  Download,
} from 'lucide-react';

// ─── Pipeline types + API ────────────────────────────────────────────────────

// When VITE_API_URL is set (local dev), the demo drives the real backend.
// On a static host (Netlify) it defaults to the Modal endpoint.
// The benchmark demos also replay bundled snapshots client-side for instant results.
const API_BASE: string = ((import.meta as any).env?.VITE_API_URL as string) ||
  'https://brendanworks--happypdf-api-fastapi-app.modal.run';
const HAS_API = API_BASE.length > 0;

type Metric = { score: number; passes: number; violations: number };
type Round = {
  round: number;
  patches_applied: number;
  passes: number;
  score: number;
  violations: number;
  gate_passed: boolean;
};
type Enhancement = { element_id: string; attribute: string; value: string };
type StageDef = { id: string; label: string };
type Job = {
  id: string;
  kind: 'replay' | 'live';
  name: string;
  status: 'running' | 'done' | 'error';
  stage: string;
  stage_index: number;
  stages: StageDef[];
  baseline: Metric | null;
  rounds: Round[];
  final: Metric | null;
  enhancements: Enhancement[];
  has_html: boolean;
  source: string | null;
  stopped_reason?: string;
  error: string | null;
};
type Snapshot = {
  id: string;
  label: string;
  source: string;
  baseline: Metric;
  rounds: Round[];
  final: Metric;
  enhancements: Enhancement[];
  stopped_reason: string;
  final_html: string;
};

const DEMOS: { id: string; label: string }[] = [
  { id: 'syllabus', label: 'Syllabus' },
  { id: 'irs_schedule_c', label: 'IRS Schedule C' },
  { id: 'navy_bulletin', label: 'Navy Bulletin' },
];

const STAGES: StageDef[] = [
  { id: 'uploading', label: 'Upload' },
  { id: 'extracting', label: 'olmOCR extraction' },
  { id: 'alt_text', label: 'Alt text generation' },
  { id: 'html', label: 'Semantic HTML' },
  { id: 'axe_baseline', label: 'axe-core baseline' },
  { id: 'round1', label: 'Peer review · Round 1' },
  { id: 'round2', label: 'Peer review · Round 2' },
  { id: 'round3', label: 'Peer review · Round 3' },
  { id: 'done', label: 'Output ready' },
];

// ─── Score ring ──────────────────────────────────────────────────────────────

function ScoreRing({
  score,
  size = 96,
  stroke = 8,
}: {
  score: number;
  size?: number;
  stroke?: number;
}) {
  const r = (size - stroke) / 2;
  const circ = 2 * Math.PI * r;
  const dash = (score / 100) * circ;
  const color = score >= 90 ? '#22c55e' : score >= 60 ? '#f59e0b' : '#ef4444';
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden="true">
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="#1e293b" strokeWidth={stroke} />
      <circle
        cx={size / 2}
        cy={size / 2}
        r={r}
        fill="none"
        stroke={color}
        strokeWidth={stroke}
        strokeDasharray={`${dash} ${circ - dash}`}
        strokeLinecap="round"
        transform={`rotate(-90 ${size / 2} ${size / 2})`}
        style={{ transition: 'stroke-dasharray 0.8s ease' }}
      />
      <text
        x="50%"
        y="50%"
        dominantBaseline="central"
        textAnchor="middle"
        fill={color}
        fontSize={size * 0.24}
        fontWeight="700"
        fontFamily="ui-monospace, monospace"
      >
        {score}
      </text>
    </svg>
  );
}

// ─── Pipeline role diagram ───────────────────────────────────────────────────

type KeyMode = 'claude' | 'openai' | 'both';

function PipelineRoleDiagram({ highlightMode }: { highlightMode: KeyMode | null }) {
  const nodes = [
    {
      id: 'ocr',
      label: 'olmOCR',
      sublabel: 'extraction',
      icon: <Cpu size={13} />,
      highlight: false,
    },
    {
      id: 'reviewers',
      label: 'Peer reviewers',
      sublabel: 'Gemini · GPT-4o · OLMo',
      icon: <Users size={13} />,
      highlight: highlightMode === 'openai' || highlightMode === 'both',
      highlightColor: 'emerald' as const,
    },
    {
      id: 'judge',
      label: 'Judge + patcher',
      sublabel: 'deduplicates · applies fixes',
      icon: <Sparkles size={13} />,
      highlight: highlightMode === 'claude' || highlightMode === 'both',
      highlightColor: 'teal' as const,
    },
    {
      id: 'axe',
      label: 'axe-core',
      sublabel: 'rescore',
      icon: <GitBranch size={13} />,
      highlight: false,
    },
  ];

  return (
    <div className="rounded-xl border border-slate-700/40 bg-slate-900/60 p-4">
      <p className="text-[10px] uppercase tracking-widest text-slate-500 font-semibold mb-3">
        Pipeline roles — use Claude, OpenAI, or both
      </p>
      <div className="flex items-stretch gap-1.5">
        {nodes.map((node, i) => (
          <div key={node.id} className="flex items-center gap-1.5 flex-1 min-w-0">
            <div
              className={`flex-1 rounded-lg px-2.5 py-2.5 border transition-all ${
                node.highlight
                  ? node.highlightColor === 'teal'
                    ? 'border-teal-500/50 bg-teal-500/10 ring-1 ring-teal-500/20'
                    : 'border-emerald-500/50 bg-emerald-500/10 ring-1 ring-emerald-500/20'
                  : 'border-slate-700/50 bg-slate-800/50'
              }`}
            >
              <div className={`mb-1 ${
                node.highlight
                  ? node.highlightColor === 'teal' ? 'text-teal-400' : 'text-emerald-400'
                  : 'text-slate-500'
              }`}>
                {node.icon}
              </div>
              <p className={`text-[10px] font-semibold leading-tight mb-0.5 ${
                node.highlight
                  ? node.highlightColor === 'teal' ? 'text-teal-300' : 'text-emerald-300'
                  : 'text-slate-300'
              }`}>
                {node.label}
              </p>
              <p className="text-[9px] text-slate-500 leading-tight">{node.sublabel}</p>
              {node.highlight && (
                <p className={`text-[9px] mt-1 font-medium leading-tight ${
                  node.highlightColor === 'teal' ? 'text-teal-400' : 'text-emerald-400'
                }`}>
                  ← your key
                </p>
              )}
            </div>
            {i < nodes.length - 1 && (
              <ArrowRight size={10} className="text-slate-700 shrink-0" />
            )}
          </div>
        ))}
      </div>
      <p className="text-[9px] text-slate-600 mt-2.5 leading-relaxed">
        Bring whichever enterprise API key you already have. Neither Claude nor OpenAI is required to use the other. Each role is independent.
      </p>
    </div>
  );
}

// ─── Demo panel ──────────────────────────────────────────────────────────────

function DemoPanel() {
  const [job, setJob] = useState<Job | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [fileName, setFileName] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [busy, setBusy] = useState(false);
  const [clientError, setClientError] = useState<string | null>(null);
  const [htmlUrl, setHtmlUrl] = useState<string | null>(null);
  const [byokKeys, setByokKeys] = useState({ anthropic: '', openai: '' });
  const [showByokSettings, setShowByokSettings] = useState(false);
  const pollRef = useRef<number | null>(null);
  const timerRef = useRef<number | null>(null);

  const stopTimers = () => {
    if (pollRef.current !== null) { window.clearInterval(pollRef.current); pollRef.current = null; }
    if (timerRef.current !== null) { window.clearTimeout(timerRef.current); timerRef.current = null; }
  };
  useEffect(() => stopTimers, []);

  const begin = (name: string) => {
    setFileName(name); setBusy(true); setJob(null); setClientError(null); setHtmlUrl(null);
  };

  // ── Client-side replay (static host): animate a bundled real snapshot ──
  const clientReplay = async (id: string, label: string) => {
    begin(`${label} (replay of a real run)`);
    let snap: Snapshot;
    try {
      const r = await fetch(`${import.meta.env.BASE_URL}snapshots/${id}.json`);
      if (!r.ok) throw new Error();
      snap = (await r.json()) as Snapshot;
    } catch {
      setBusy(false); setClientError('Could not load the demo snapshot.'); return;
    }
    const idxOf = (sid: string) => STAGES.findIndex((s) => s.id === sid);
    let cur: Job = {
      id, kind: 'replay', name: snap.label, status: 'running', stage: 'uploading',
      stage_index: 0, stages: STAGES, baseline: null, rounds: [], final: null,
      enhancements: [], has_html: false, source: snap.source, error: null,
    };
    const steps: { stage: string; delay: number; apply?: () => void }[] = [
      { stage: 'uploading', delay: 350 },
      { stage: 'extracting', delay: 1000 },
      { stage: 'alt_text', delay: 800 },
      { stage: 'html', delay: 600 },
      { stage: 'axe_baseline', delay: 700, apply: () => { cur.baseline = snap.baseline; } },
    ];
    snap.rounds.forEach((rnd) =>
      steps.push({ stage: `round${rnd.round}`, delay: 850, apply: () => { cur.rounds = [...cur.rounds, rnd]; } }),
    );
    steps.push({
      stage: 'done', delay: 300, apply: () => {
        cur.final = snap.final; cur.enhancements = snap.enhancements;
        cur.stopped_reason = snap.stopped_reason; cur.has_html = true; cur.status = 'done';
      },
    });
    let i = 0;
    const tick = () => {
      const st = steps[i];
      cur = { ...cur, stage: st.stage, stage_index: idxOf(st.stage), rounds: [...cur.rounds] };
      if (st.apply) st.apply();
      setJob({ ...cur, rounds: [...cur.rounds] });
      i += 1;
      if (i < steps.length) { timerRef.current = window.setTimeout(tick, st.delay); }
      else {
        setBusy(false);
        setHtmlUrl(URL.createObjectURL(new Blob([snap.final_html], { type: 'text/html' })));
      }
    };
    tick();
  };

  // ── API-driven (local dev with the backend running) ──
  const poll = (id: string) => {
    stopTimers();
    pollRef.current = window.setInterval(async () => {
      try {
        const r = await fetch(`${API_BASE}/api/jobs/${id}`);
        if (!r.ok) return;
        const j = (await r.json()) as Job;
        setJob(j);
        if (j.status === 'done' || j.status === 'error') { stopTimers(); setBusy(false); }
      } catch { /* keep polling */ }
    }, 600);
  };
  const apiLive = async (file: File) => {
    begin(file.name);
    try {
      const fd = new FormData();
      fd.append('file', file);
      if (byokKeys.anthropic) fd.append('anthropic_api_key', byokKeys.anthropic);
      if (byokKeys.openai) fd.append('openai_api_key', byokKeys.openai);
      const r = await fetch(`${API_BASE}/api/jobs/live`, { method: 'POST', body: fd });
      if (!r.ok) throw new Error();
      const { job_id } = (await r.json()) as { job_id: string };
      setJobId(job_id); poll(job_id);
    } catch { setBusy(false); setClientError(`Couldn't start a live job at ${API_BASE}.`); }
  };

  // Demos always replay the bundled snapshots client-side — free, instant, and
  // independent of the (paid) live API. Only PDF uploads use the API.
  const startDemo = (id: string, label: string) => clientReplay(id, label);
  const onDropFile = (file: File) => {
    if (HAS_API) { apiLive(file); }
    else { setClientError('Live upload runs in self-hosted mode. The demos below are real recorded runs you can replay instantly.'); }
  };

  const reset = () => {
    stopTimers();
    setJob(null); setJobId(null); setFileName(null); setBusy(false); setClientError(null); setHtmlUrl(null);
  };

  const idle = !busy && !job && !clientError;
  const stages = job?.stages ?? [];
  const current = job?.stage_index ?? -1;
  const done = job?.status === 'done';
  const hasResults = !!job?.baseline;
  const maxRound = done && job ? Math.max(1, job.rounds.length) : 3;
  const htmlHref = HAS_API && jobId && job?.kind === 'live' ? `${API_BASE}/api/jobs/${jobId}/html` : htmlUrl;

  return (
    <div className="bg-slate-900 rounded-2xl border border-slate-700/60 overflow-hidden">
      <div className="flex items-center gap-2 px-4 py-3 bg-slate-800/80 border-b border-slate-700/60">
        <span className="w-3 h-3 rounded-full bg-rose-500/80" />
        <span className="w-3 h-3 rounded-full bg-amber-400/80" />
        <span className="w-3 h-3 rounded-full bg-emerald-500/80" />
        <span className="ml-3 text-xs font-mono text-slate-400">happypdf — pipeline</span>
        {!idle && (
          <button onClick={reset} className="ml-auto text-slate-500 hover:text-slate-300 transition-colors" aria-label="Reset demo">
            <X size={14} />
          </button>
        )}
      </div>

      <div className="p-6 space-y-6">
        {idle ? (
          <>
            {HAS_API && (
              <div className="bg-slate-800/50 border border-slate-700/50 rounded-lg p-4 space-y-3">
                <button
                  type="button"
                  onClick={() => setShowByokSettings(!showByokSettings)}
                  className="text-xs text-slate-400 hover:text-slate-300 font-medium flex items-center gap-2 transition-colors"
                >
                  <Key size={14} />
                  {showByokSettings ? 'Hide' : 'Add'} your own API keys (optional)
                </button>
                {showByokSettings && (
                  <div className="space-y-2 pt-2 border-t border-slate-700/50">
                    <input
                      type="password"
                      placeholder="Anthropic API key (optional)"
                      value={byokKeys.anthropic}
                      onChange={(e) => setByokKeys({ ...byokKeys, anthropic: e.target.value })}
                      className="w-full px-3 py-2 bg-slate-900 border border-slate-600/50 rounded text-xs text-slate-300 placeholder-slate-600 focus:outline-none focus:border-teal-400/50"
                    />
                    <input
                      type="password"
                      placeholder="OpenAI API key (optional)"
                      value={byokKeys.openai}
                      onChange={(e) => setByokKeys({ ...byokKeys, openai: e.target.value })}
                      className="w-full px-3 py-2 bg-slate-900 border border-slate-600/50 rounded text-xs text-slate-300 placeholder-slate-600 focus:outline-none focus:border-teal-400/50"
                    />
                    <p className="text-xs text-slate-500">⚠️ Keys stored locally in your browser. Not transmitted to happypdf servers.</p>
                    {(byokKeys.anthropic || byokKeys.openai) && (
                      <button
                        type="button"
                        onClick={() => setByokKeys({ anthropic: '', openai: '' })}
                        className="text-xs text-slate-400 hover:text-slate-300 underline transition-colors"
                      >
                        Clear all keys
                      </button>
                    )}
                  </div>
                )}
              </div>
            )}
            {HAS_API ? (
              <div
                onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
                onDragLeave={() => setDragOver(false)}
                onDrop={(e) => { e.preventDefault(); setDragOver(false); const f = e.dataTransfer.files[0]; if (f) onDropFile(f); }}
                className={`border-2 border-dashed rounded-xl p-10 text-center transition-all cursor-pointer ${dragOver ? 'border-teal-400 bg-teal-400/5' : 'border-slate-600 hover:border-slate-500 hover:bg-slate-800/40'}`}
                onClick={() => document.getElementById('pdf-upload')?.click()}
              >
                <Upload className="mx-auto mb-3 text-slate-500" size={32} />
                <p className="text-slate-300 font-medium mb-1">Drop a PDF to run the live pipeline</p>
                <p className="text-slate-500 text-sm mb-1">olmOCR → alt text → semantic HTML → axe-core → live-reviewer loop</p>
                <p className="text-slate-600 text-xs">Live runs take a few minutes and call real models.</p>
                <p className="text-slate-500 text-xs mt-3"><button type="button" className="text-teal-400 hover:text-teal-300 underline" onClick={(e) => { e.stopPropagation(); document.getElementById('pdf-upload')?.click(); }}>or click to upload from your computer</button></p>
                <input id="pdf-upload" type="file" accept=".pdf" className="hidden" onChange={(e) => { if (e.target.files?.[0]) onDropFile(e.target.files[0]); }} />
              </div>
            ) : (
              <div className="border-2 border-dashed border-slate-700 rounded-xl p-8 text-center">
                <Layers className="mx-auto mb-3 text-slate-600" size={28} />
                <p className="text-slate-300 font-medium mb-1">Replay a real benchmark run</p>
                <p className="text-slate-500 text-sm">olmOCR → alt text → semantic HTML → axe-core → live-reviewer loop.</p>
                <p className="text-slate-600 text-xs mt-1">Live PDF upload runs in self-hosted mode.</p>
              </div>
            )}
            <div>
              <p className="text-xs text-slate-500 mb-2">Pick a document — these are the actual recorded outputs:</p>
              <div className="flex flex-wrap gap-2">
                {DEMOS.map((d) => (
                  <button key={d.id} onClick={() => startDemo(d.id, d.label)} className="text-xs font-mono px-3 py-1.5 rounded-md bg-slate-700 text-teal-400 hover:bg-slate-600 transition-colors">
                    {d.label} →
                  </button>
                ))}
              </div>
            </div>
          </>
        ) : clientError ? (
          <div className="text-center py-8 space-y-3">
            <AlertTriangle className="mx-auto text-amber-400" size={28} />
            <p className="text-slate-300 text-sm">{clientError}</p>
            <button onClick={reset} className="text-xs font-mono px-3 py-1.5 rounded-md bg-slate-700 text-slate-200 hover:bg-slate-600">Back to demos</button>
          </div>
        ) : (
          <div className="space-y-5">
            <div className="flex items-center gap-3 px-4 py-3 bg-slate-800 rounded-lg border border-slate-700/60">
              <FileText size={16} className="text-teal-400 shrink-0" />
              <span className="text-sm text-slate-300 font-mono truncate">{fileName}</span>
              {done && (
                <span className="ml-auto text-xs text-emerald-400 font-medium flex items-center gap-1">
                  <CheckCircle size={12} /> Complete
                </span>
              )}
            </div>

            <div className="space-y-1.5">
              {stages
                .filter((s) => s.id !== 'uploading' && !(s.id.startsWith('round') && Number(s.id.slice(5)) > maxRound))
                .map((s) => {
                  const i = stages.findIndex((x) => x.id === s.id);
                  const isDone = i < current || (s.id === 'done' && done);
                  const active = i === current && !done;
                  return (
                    <div key={s.id} className={`flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-all ${active ? 'bg-teal-400/10 border border-teal-400/20' : isDone ? 'opacity-60' : 'opacity-30'}`}>
                      {isDone ? (
                        <CheckCircle size={14} className="text-emerald-400 shrink-0" />
                      ) : active ? (
                        <RefreshCw size={14} className="text-teal-400 animate-spin shrink-0" />
                      ) : (
                        <div className="w-3.5 h-3.5 rounded-full border border-slate-600 shrink-0" />
                      )}
                      <span className={isDone ? 'text-slate-300' : active ? 'text-teal-300' : 'text-slate-500'}>{s.label}</span>
                    </div>
                  );
                })}
            </div>

            {job?.status === 'error' && (
              <div className="text-xs text-rose-300 bg-rose-500/10 border border-rose-500/30 rounded-lg px-3 py-2 font-mono">{job.error}</div>
            )}

            {hasResults && job && (
              <div className="border border-slate-700/60 rounded-xl p-4 space-y-3">
                <p className="text-xs text-slate-500 font-medium uppercase tracking-wider">Automated check coverage (axe-core)</p>
                <div className="flex items-center justify-around">
                  <div className="text-center space-y-1">
                    <ScoreRing score={job.baseline!.score} size={72} stroke={7} />
                    <p className="text-xs text-slate-500">Baseline</p>
                    <p className="text-xs text-slate-400 font-mono">{job.baseline!.passes} passing</p>
                  </div>
                  <ArrowRight size={14} className="text-slate-600" />
                  <div className="text-center space-y-1">
                    <ScoreRing score={(job.final ?? job.baseline!).score} size={72} stroke={7} />
                    <p className="text-xs text-slate-500">{done ? 'Final' : 'Latest'}</p>
                    <p className="text-xs text-slate-400 font-mono">{(job.final ?? job.baseline!).passes} passing</p>
                  </div>
                </div>
                <p className="text-[11px] text-slate-500 text-center leading-relaxed">
                  {job.baseline!.violations} violations at baseline — the loop <span className="text-slate-400">adds ARIA</span>, it doesn't fix broken HTML.
                </p>
              </div>
            )}

            {hasResults && job && (
              <div className="space-y-1.5">
                <p className="text-xs text-slate-500 font-medium uppercase tracking-wider px-1">ARIA enhancements added</p>
                {job.enhancements.length === 0 ? (
                  <p className="text-xs text-slate-500 px-1">Baseline already passes — no enhancements suggested.</p>
                ) : (
                  job.enhancements.map((e, i) => (
                    <div key={i} className="flex items-center gap-3 px-3 py-2.5 rounded-lg text-xs border border-emerald-500/20 bg-emerald-500/5">
                      <CheckCircle size={12} className="text-emerald-400 shrink-0" />
                      <span className="font-mono text-emerald-300 truncate">{e.attribute}="{e.value}"</span>
                      <span className="ml-auto font-mono text-slate-600 truncate max-w-[35%]">{e.element_id}</span>
                    </div>
                  ))
                )}
              </div>
            )}

            {done && job && job.rounds.length > 0 && (
              <p className="text-[11px] text-slate-500 text-center leading-relaxed">
                {job.stopped_reason === 'converged' ? 'Converged' : job.stopped_reason} in {job.rounds.length} round
                {job.rounds.length > 1 ? 's' : ''} · gate passed every round{job.source ? ` · ${job.source}` : ''}
              </p>
            )}

            {done && job && job.has_html && htmlHref && (
              <div className="space-y-3 pt-1">
                <div className="flex gap-2">
                  <a href={htmlHref} target="_blank" rel="noopener noreferrer" className="flex-1 flex items-center justify-center gap-2 px-4 py-2.5 bg-teal-500 hover:bg-teal-400 text-slate-900 font-semibold text-sm rounded-lg transition-colors">
                    <Code2 size={14} />
                    View output HTML
                  </a>
                  <button onClick={() => {
                    const link = document.createElement('a');
                    link.href = htmlHref;
                    link.download = fileName?.replace(/\.[^/.]+$/, '') || 'output';
                    document.body.appendChild(link);
                    link.click();
                    document.body.removeChild(link);
                  }} className="flex items-center justify-center gap-2 px-4 py-2.5 bg-slate-700 hover:bg-slate-600 text-slate-200 text-sm rounded-lg transition-colors">
                    <Download size={14} />
                    Download
                  </button>
                </div>
                {job.kind === 'replay' && (
                  <a href={`https://github.com/BrendanWorks/happypdf/raw/main/benchmark/${job.id === 'syllabus' ? 'syllabus_NOTaccessible' : job.id === 'navy_bulletin' ? 'navy_bulletin' : 'irs_schedule_c'}.pdf`} target="_blank" rel="noopener noreferrer" className="block text-center text-xs text-slate-400 hover:text-slate-300 transition-colors">
                    ↓ Download original PDF
                  </a>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}


// ─── Deployment mode card ────────────────────────────────────────────────────

function ModeCard({
  icon,
  label,
  badge,
  badgeColor,
  lines,
}: {
  icon: React.ReactNode;
  label: string;
  badge: string;
  badgeColor: string;
  lines: string[];
}) {
  return (
    <div className="bg-slate-900 border border-slate-700/60 rounded-2xl p-6 flex flex-col gap-4 hover:border-slate-600 transition-colors">
      <div className="flex items-start justify-between">
        <div className="p-2.5 bg-slate-800 rounded-xl text-teal-400">{icon}</div>
        <span className={`text-xs font-semibold px-2.5 py-1 rounded-full ${badgeColor}`}>{badge}</span>
      </div>
      <div>
        <h3 className="font-semibold text-slate-100 mb-3">{label}</h3>
        <ul className="space-y-2">
          {lines.map((l) => (
            <li key={l} className="flex items-start gap-2 text-sm text-slate-400">
              <ChevronRight size={14} className="text-slate-600 mt-0.5 shrink-0" />
              {l}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

// ─── Feature row ─────────────────────────────────────────────────────────────

function FeatureRow({
  icon,
  title,
  body,
}: {
  icon: React.ReactNode;
  title: string;
  body: string;
}) {
  return (
    <div className="flex gap-4">
      <div className="p-2.5 bg-slate-800 rounded-xl text-teal-400 shrink-0 h-fit">{icon}</div>
      <div>
        <h3 className="font-semibold text-slate-100 mb-1">{title}</h3>
        <p className="text-slate-400 text-sm leading-relaxed">{body}</p>
      </div>
    </div>
  );
}

// ─── FAQ item ────────────────────────────────────────────────────────────────

function FaqItem({ q, a }: { q: string; a: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="border-b border-slate-800">
      <button
        className="w-full text-left py-4 flex items-center justify-between gap-4 text-slate-200 hover:text-white transition-colors"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
      >
        <span className="font-medium">{q}</span>
        <ChevronDown
          size={16}
          className={`text-slate-500 shrink-0 transition-transform ${open ? 'rotate-180' : ''}`}
        />
      </button>
      {open && (
        <p className="pb-4 text-sm text-slate-400 leading-relaxed">{a}</p>
      )}
    </div>
  );
}

// ─── Main app ────────────────────────────────────────────────────────────────

export default function App() {
  return (
    <div className="min-h-screen bg-slate-950 text-slate-200 font-sans antialiased">
      {/* ── Nav ─────────────────────────────────────────────────────────── */}
      <header className="sticky top-0 z-50 border-b border-slate-800/80 bg-slate-950/90 backdrop-blur-sm">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 h-14 flex items-center justify-between">
          <a href="/" className="flex items-center gap-2.5 group" aria-label="HappyPDF home">
            <div className="w-7 h-7 bg-teal-500 rounded-lg flex items-center justify-center">
              <FileText size={15} className="text-slate-900" />
            </div>
            <span className="font-bold text-slate-100 tracking-tight">
              happy<span className="text-teal-400">pdf</span>
            </span>
            <span className="text-[10px] font-mono text-slate-500 bg-slate-800 px-1.5 py-0.5 rounded ml-0.5">
              WCAG 2.2
            </span>
          </a>

          <nav className="hidden md:flex items-center gap-6 text-sm text-slate-400">
            <a href="#how-it-works" className="hover:text-slate-200 transition-colors">How it works</a>
            <a href="#modes" className="hover:text-slate-200 transition-colors">Deployment</a>
            <a href="#faq" className="hover:text-slate-200 transition-colors">FAQ</a>
            <a
              href="https://github.com/BrendanWorks/happypdf"
              className="flex items-center gap-1.5 hover:text-slate-200 transition-colors"
              rel="noopener noreferrer"
            >
              <Github size={14} />
              GitHub
            </a>
          </nav>

          <a
            href="#demo"
            className="text-sm font-semibold px-4 py-1.5 rounded-lg bg-teal-500 hover:bg-teal-400 text-slate-900 transition-colors"
          >
            Try demo
          </a>
        </div>
      </header>

      <main>
        {/* ── Hero ────────────────────────────────────────────────────────── */}
        <section className="relative overflow-hidden pt-20 pb-16 sm:pt-28 sm:pb-24">
          {/* Ambient glow */}
          <div
            aria-hidden="true"
            className="pointer-events-none absolute inset-0 overflow-hidden"
          >
            <div className="absolute -top-24 left-1/2 -translate-x-1/2 w-[700px] h-[400px] rounded-full bg-teal-500/5 blur-3xl" />
          </div>

          <div className="relative max-w-6xl mx-auto px-4 sm:px-6">
            {/* Badge */}
            <div className="flex justify-center mb-6">
              <span className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-slate-800 border border-slate-700/60 text-xs text-slate-400">
                <span className="w-1.5 h-1.5 rounded-full bg-teal-400 animate-pulse" />
                Built on&nbsp;
                <span className="text-teal-400 font-medium">olmOCR · OLMo · Ai2</span>
                &nbsp;open models
              </span>
            </div>

            <div className="grid lg:grid-cols-2 gap-12 items-center">
              <div className="text-center lg:text-left">
                <h1 className="text-4xl sm:text-5xl lg:text-[3.25rem] font-extrabold text-white leading-[1.1] tracking-tight mb-6">
                  PDF&nbsp;→&nbsp;accessible&nbsp;HTML.{' '}
                  <span className="text-teal-400">Validated.</span>{' '}
                  <span className="text-slate-400">Open.</span>
                </h1>
                <p className="text-slate-400 text-lg leading-relaxed mb-8 max-w-xl mx-auto lg:mx-0">
                  HappyPDF converts inaccessible PDFs into WCAG 2.2 AA&ndash;validated HTML using a
                  multi-model iterative remediation pipeline — powered entirely by open Ai2 models.
                </p>

                <div className="flex flex-col sm:flex-row gap-3 justify-center lg:justify-start">
                  <a
                    href="#demo"
                    className="flex items-center justify-center gap-2 px-6 py-3 bg-teal-500 hover:bg-teal-400 text-slate-900 font-semibold rounded-xl transition-colors"
                  >
                    Try your own pdf!
                    <ArrowRight size={16} />
                  </a>
                  <a
                    href="https://github.com/BrendanWorks/happypdf"
                    rel="noopener noreferrer"
                    className="flex items-center justify-center gap-2 px-6 py-3 bg-slate-800 hover:bg-slate-700 text-slate-200 font-medium rounded-xl border border-slate-700/60 transition-colors"
                  >
                    <Github size={16} />
                    View on GitHub
                  </a>
                </div>

                {/* Mini stats */}
                <div className="mt-10 flex flex-wrap gap-6 justify-center lg:justify-start">
                  {[
                    { val: '97%', label: 'avg. final score' },
                    { val: '3', label: 'max remediation rounds' },
                    { val: '0', label: 'API key needed*' },
                  ].map(({ val, label }) => (
                    <div key={label} className="text-center lg:text-left">
                      <p className="text-2xl font-bold text-teal-400 font-mono">{val}</p>
                      <p className="text-xs text-slate-500 mt-0.5">{label}</p>
                    </div>
                  ))}
                </div>
                <p className="text-xs text-slate-600 mt-2 text-center lg:text-left">
                  * Self-hosted mode. Bring your own keys for max quality.
                </p>
              </div>

              {/* Demo panel */}
              <div id="demo" className="w-full">
                <DemoPanel />
              </div>
            </div>
          </div>
        </section>

        {/* ── Caveat banner ────────────────────────────────────────────────── */}
        <div className="bg-amber-500/10 border-y border-amber-500/20">
          <div className="max-w-6xl mx-auto px-4 sm:px-6 py-3 flex items-start gap-3 text-sm text-amber-300">
            <AlertTriangle size={16} className="mt-0.5 shrink-0" />
            <span>
              axe-core automated checks cover&nbsp;
              <strong className="text-amber-200">30–40% of WCAG requirements.</strong> HappyPDF
              reports automated check coverage, not certified WCAG conformance. Manual review is
              still required for full compliance.
            </span>
          </div>
        </div>

        {/* ── How it works ─────────────────────────────────────────────────── */}
        <section id="how-it-works" className="py-20 sm:py-28">
          <div className="max-w-6xl mx-auto px-4 sm:px-6">
            <div className="text-center mb-14">
              <p className="text-xs font-semibold uppercase tracking-widest text-teal-500 mb-3">
                Pipeline
              </p>
              <h2 className="text-3xl sm:text-4xl font-extrabold text-white tracking-tight">
                How it works
              </h2>
              <p className="mt-4 text-slate-400 max-w-xl mx-auto">
                An iterative multi-model loop — not a single-pass linter. Each round, peer
                reviewers flag issues; Claude judges and patches; axe-core rescores.
              </p>
            </div>

            {/* Architecture diagram */}
            <div className="mb-16 max-w-2xl mx-auto">
              <PipelineRoleDiagram highlightMode={null} />
            </div>

            {/* Pipeline steps */}
            <div className="relative">
              {/* Connector line */}
              <div
                aria-hidden="true"
                className="hidden lg:block absolute left-1/2 -translate-x-1/2 top-8 bottom-8 w-px bg-gradient-to-b from-teal-500/0 via-teal-500/30 to-teal-500/0"
              />

              <div className="space-y-4 lg:space-y-0 lg:grid lg:grid-cols-1 lg:gap-0">
                {[
                  {
                    step: '01',
                    title: 'olmOCR extraction',
                    body: 'Allenai/olmOCR-2-7B-1025 (Qwen2.5-VL backbone) runs on Modal H100 for pure vision-based PDF extraction — no fragile text-layer anchoring. The same model generates alt text for every image with a screen-reader–tuned prompt.',
                    side: 'left',
                  },
                  {
                    step: '02',
                    title: 'Semantic HTML generation',
                    body: 'Extraction markdown becomes WCAG-scaffolded HTML5: skip link, <main> landmark, lang attribute, deterministic data-ir-id on every element for stable patch targeting across rounds.',
                    side: 'right',
                  },
                  {
                    step: '03',
                    title: 'axe-core baseline',
                    body: 'Playwright drives a real Chromium instance — not a DOM parser. Every axe-core result is labeled "automated check coverage," never misrepresented as full WCAG conformance.',
                    side: 'left',
                  },
                  {
                    step: '04',
                    title: 'Multi-model peer review (×3 rounds)',
                    body: 'Gemini, GPT-4o, and OLMo-2 review HTML chunks in parallel against 79 validated WCAG 2.2 criteria. Claude deduplicates findings, flags hallucinated criteria, and produces a typed patch manifest. Deterministic Python applies patches. Rounds stop early when no critical violations remain.',
                    side: 'right',
                  },
                  {
                    step: '05',
                    title: 'Output package',
                    body: 'Accessible HTML + human-readable review manifest + plain-English summary of every fix, verification, and unresolved finding.',
                    side: 'left',
                  },
                ].map(({ step, title, body, side }) => (
                  <div
                    key={step}
                    className={`lg:flex ${side === 'right' ? 'lg:flex-row-reverse' : ''} items-center gap-8 py-6`}
                  >
                    <div className={`lg:w-[calc(50%-2rem)] ${side === 'right' ? 'lg:pl-10' : 'lg:pr-10'}`}>
                      <div className="bg-slate-900 border border-slate-700/60 rounded-2xl p-6 hover:border-slate-600 transition-colors">
                        <p className="text-xs font-mono text-teal-500 mb-2">{step}</p>
                        <h3 className="font-semibold text-slate-100 mb-2">{title}</h3>
                        <p className="text-sm text-slate-400 leading-relaxed">{body}</p>
                      </div>
                    </div>
                    {/* Center step dot */}
                    <div className="hidden lg:flex w-16 shrink-0 justify-center">
                      <div className="w-3 h-3 rounded-full bg-teal-500 ring-4 ring-teal-500/20" />
                    </div>
                    <div className="hidden lg:block lg:w-[calc(50%-2rem)]" />
                  </div>
                ))}
              </div>
            </div>
          </div>
        </section>

        {/* ── Features ─────────────────────────────────────────────────────── */}
        <section className="py-20 sm:py-28 bg-slate-900/40 border-y border-slate-800/60">
          <div className="max-w-6xl mx-auto px-4 sm:px-6">
            <div className="text-center mb-14">
              <p className="text-xs font-semibold uppercase tracking-widest text-teal-500 mb-3">
                What makes it different
              </p>
              <h2 className="text-3xl sm:text-4xl font-extrabold text-white tracking-tight">
                Not another single-pass tool
              </h2>
            </div>

            <div className="grid md:grid-cols-2 gap-8">
              <FeatureRow
                icon={<Eye size={18} />}
                title="Vision-first extraction"
                body="olmOCR is document-specialized, not a repurposed general VLM. It handles two-column layouts, form grids, scanned images, and historical documents where text-layer tools fail."
              />
              <FeatureRow
                icon={<ShieldCheck size={18} />}
                title="Hallucination gating"
                body="Every peer reviewer output is validated against 79 real WCAG 2.2 criterion IDs. Invented criteria are flagged with hallucinated: true — never silently removed or applied."
              />
              <FeatureRow
                icon={<BarChart3 size={18} />}
                title="Honest scoring"
                body='Score progression is labeled "automated check coverage" throughout. The product never claims automated WCAG conformance — because no automated tool can.'
              />
              <FeatureRow
                icon={<Zap size={18} />}
                title="Deterministic patch application"
                body="Patches target elements by data-ir-id, not CSS selectors. Stable across DOM restructuring. A content preservation gate verifies text coverage, image count, and heading structure before accepting each round."
              />
              <FeatureRow
                icon={<Layers size={18} />}
                title="Typed patch manifest"
                body="Every change is logged as deterministic, llm_safe, or needs_human. The audit trail is a first-class output — not a side effect."
              />
              <FeatureRow
                icon={<Code2 size={18} />}
                title="Fully open source"
                body="Built on public Ai2 models (olmOCR, OLMo). The entire pipeline, scoring formula, and patch logic are in the open repository. No black boxes."
              />
            </div>
          </div>
        </section>

        {/* ── Deployment modes ─────────────────────────────────────────────── */}
        <section id="modes" className="py-20 sm:py-28">
          <div className="max-w-6xl mx-auto px-4 sm:px-6">
            <div className="text-center mb-14">
              <p className="text-xs font-semibold uppercase tracking-widest text-teal-500 mb-3">
                Deployment
              </p>
              <h2 className="text-3xl sm:text-4xl font-extrabold text-white tracking-tight">
                Three ways to run it
              </h2>
              <p className="mt-4 text-slate-400 max-w-xl mx-auto">
                The same orchestration code, the same audit trail. Choose the model layer that fits
                your budget and procurement reality.
              </p>
            </div>

            <div className="grid md:grid-cols-3 gap-6">
              <ModeCard
                icon={<Server size={18} />}
                label="Self-hosted / open source"
                badge="Free"
                badgeColor="bg-slate-700 text-slate-300"
                lines={[
                  'All open-weight models (OLMo, Llama, Mistral)',
                  'Runs on Modal or your own hardware',
                  'Zero cost per conversion',
                  'Lower quality ceiling than proprietary APIs',
                ]}
              />
              <ModeCard
                icon={<Globe size={18} />}
                label="Hosted demo"
                badge="Pay-per-use"
                badgeColor="bg-teal-500/10 text-teal-400 border border-teal-500/20"
                lines={[
                  'Claude as judge + fixer',
                  'Gemini, GPT-4o, OLMo as peer reviewers',
                  'Best output quality',
                  'Cost scales with document size and rounds',
                ]}
              />
              <ModeCard
                icon={<Key size={18} />}
                label="BYOK / enterprise"
                badge="Differentiator"
                badgeColor="bg-amber-500/10 text-amber-400 border border-amber-500/20"
                lines={[
                  'Bring your existing Claude / ChatGPT enterprise credentials',
                  'Zero incremental cost on already-approved API access',
                  'No new procurement friction',
                  'No identified competitor has built this',
                ]}
              />
            </div>

            <p className="mt-6 text-center text-xs text-slate-600">
              The real barrier to enterprise adoption is procurement friction, not technical
              capability. BYOK sidesteps it.
            </p>
          </div>
        </section>

        {/* ── Prior art / credibility ──────────────────────────────────────── */}
        <section className="py-16 bg-slate-900/40 border-y border-slate-800/60">
          <div className="max-w-4xl mx-auto px-4 sm:px-6">
            <p className="text-xs font-semibold uppercase tracking-widest text-teal-500 mb-8 text-center">
              Research context
            </p>
            <div className="grid sm:grid-cols-2 gap-6">
              {[
                {
                  tag: "Ai2 · ASSETS '21",
                  title: 'SciA11y',
                  authors: 'Wang, Cachola, et al.',
                  note: 'Converts scientific PDFs to accessible HTML. HappyPDF extends this direction to general and government documents, adding the iterative WCAG validation loop SciA11y identified as future work.',
                },
                {
                  tag: 'Ai2 · arXiv 2601.10611',
                  title: 'olmOCR',
                  authors: 'Poznanski et al.',
                  note: "Production PDF extraction via pure vision. HappyPDF builds directly on olmOCR's extraction foundation and adds multi-model WCAG remediation.",
                },
              ].map(({ tag, title, authors, note }) => (
                <div
                  key={title}
                  className="bg-slate-900 border border-slate-700/60 rounded-2xl p-6 hover:border-slate-600 transition-colors"
                >
                  <p className="text-xs font-mono text-teal-500 mb-1">{tag}</p>
                  <h3 className="font-semibold text-slate-100 mb-0.5">{title}</h3>
                  <p className="text-xs text-slate-500 mb-3">{authors}</p>
                  <p className="text-sm text-slate-400 leading-relaxed">{note}</p>
                  <a
                    href="#"
                    className="mt-3 inline-flex items-center gap-1 text-xs text-teal-500 hover:text-teal-400 transition-colors"
                  >
                    Read paper <ExternalLink size={10} />
                  </a>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* ── FAQ ─────────────────────────────────────────────────────────── */}
        <section id="faq" className="py-20 sm:py-28">
          <div className="max-w-2xl mx-auto px-4 sm:px-6">
            <div className="text-center mb-12">
              <p className="text-xs font-semibold uppercase tracking-widest text-teal-500 mb-3">
                FAQ
              </p>
              <h2 className="text-3xl sm:text-4xl font-extrabold text-white tracking-tight">
                Common questions
              </h2>
            </div>

            <div>
              <FaqItem
                q="Does HappyPDF guarantee WCAG conformance?"
                a="No. Automated tools including axe-core cover roughly 30–40% of WCAG requirements. HappyPDF reports automated check coverage, not certified conformance. The score is a meaningful signal for iterative improvement, but manual review by an accessibility specialist is required for legal or compliance declarations."
              />
              <FaqItem
                q="What document types work best?"
                a="Dense digital PDFs (government forms, regulations, academic papers) produce the best results — olmOCR was trained specifically on these. Scanned historical documents also work via pure vision, though quality depends on scan quality. Complex multi-column layouts, mixed-content documents, and tables with merged cells are all handled."
              />
              <FaqItem
                q="What does BYOK mean and why does it matter?"
                a="BYOK is Bring Your Own Keys — you connect your existing Claude or ChatGPT enterprise API credentials. If your organization already pays for Claude or GPT-4o API access through enterprise agreements, HappyPDF uses those credentials at no additional cost. This sidesteps the procurement process that blocks most AI tools from reaching enterprise teams."
              />
              <FaqItem
                q="How is this different from DocAccess or SentraCheck?"
                a="Commercial tools are closed-box, paid per conversion, and don't expose their logic. HappyPDF is fully open source — every patch, every reviewer score, every violation flag is in the audit trail. You can inspect exactly what changed and why."
              />
              <FaqItem
                q="Why three rounds maximum?"
                a="Stopping criteria are issue-based, not score-based: no critical violations + no content preservation failures + no reading order regressions. The round cap prevents over-remediation. In practice the IRS Schedule C benchmark reaches all hard gates in two rounds."
              />
            </div>
          </div>
        </section>

        {/* ── CTA ─────────────────────────────────────────────────────────── */}
        <section className="py-20 bg-slate-900/40 border-t border-slate-800/60">
          <div className="max-w-2xl mx-auto px-4 sm:px-6 text-center">
            <h2 className="text-3xl sm:text-4xl font-extrabold text-white tracking-tight mb-4">
              Make your PDFs accessible.
            </h2>
            <p className="text-slate-400 mb-8 leading-relaxed">
              No account. No credit card. Drop a PDF and see the pipeline run in your browser.
            </p>
            <div className="flex flex-col sm:flex-row gap-3 justify-center">
              <a
                href="#demo"
                className="flex items-center justify-center gap-2 px-8 py-3.5 bg-teal-500 hover:bg-teal-400 text-slate-900 font-semibold rounded-xl transition-colors"
              >
                Run the demo
                <ArrowRight size={16} />
              </a>
              <a
                href="https://github.com/BrendanWorks/happypdf"
                rel="noopener noreferrer"
                className="flex items-center justify-center gap-2 px-8 py-3.5 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-xl border border-slate-700/60 transition-colors font-medium"
              >
                <Github size={16} />
                Star on GitHub
              </a>
            </div>
          </div>
        </section>
      </main>

      {/* ── Footer ──────────────────────────────────────────────────────────── */}
      <footer className="border-t border-slate-800/60 py-10">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 flex flex-col sm:flex-row items-center justify-between gap-4 text-sm text-slate-500">
          <div className="flex items-center gap-2">
            <div className="w-5 h-5 bg-teal-500 rounded flex items-center justify-center">
              <FileText size={10} className="text-slate-900" />
            </div>
            <span>
              happy<span className="text-teal-500">pdf</span>.org
            </span>
          </div>

          <div className="flex items-center gap-6">
            <a href="https://pointcheck.org/" rel="noopener noreferrer" className="hover:text-slate-300 transition-colors flex items-center gap-1">
              PointCheck <ExternalLink size={11} />
            </a>
            <a href="#" className="hover:text-slate-300 transition-colors">
              GitHub
            </a>
            <a href="#" className="hover:text-slate-300 transition-colors">
              Research
            </a>
          </div>

          <p className="text-slate-600 text-xs text-center sm:text-right">
            Built on Ai2 open models.&nbsp;
            <a href="https://allenai.org" rel="noopener noreferrer" className="hover:text-slate-400 transition-colors underline underline-offset-2">
              allenai.org
            </a>
          </p>
        </div>
      </footer>
    </div>
  );
}
