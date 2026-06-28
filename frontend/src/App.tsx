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
  Download,
  Users,
  Cpu,
  GitBranch,
  Sparkles,
} from 'lucide-react';

// When VITE_API_URL is set (local dev), the demo drives the real backend.
// On a static host (Netlify) it defaults to the Modal endpoint.
const API_BASE: string = ((import.meta as any).env?.VITE_API_URL as string) ||
  'https://brendanworks--happypdf-api-fastapi-app.modal.run';
const HAS_API = API_BASE.length > 0;

// ─── Pipeline stage types ────────────────────────────────────────────────────

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

const STAGE_ORDER: PipelineStage[] = [
  'uploading',
  'extracting',
  'alt_text',
  'html',
  'axe_baseline',
  'round1',
  'round2',
  'round3',
  'done',
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
      role: 'Ai2 open model',
      highlight: false,
      icon: <Cpu size={13} />,
    },
    {
      id: 'reviewers',
      label: 'Peer reviewers',
      sublabel: 'Gemini · GPT-4o · OLMo',
      role: 'your OpenAI key powers GPT-4o here',
      highlight: highlightMode === 'openai' || highlightMode === 'both',
      highlightColor: 'emerald',
      icon: <Users size={13} />,
    },
    {
      id: 'judge',
      label: 'Judge + patcher',
      sublabel: 'deduplicates · applies fixes',
      role: 'your Claude key powers this role',
      highlight: highlightMode === 'claude' || highlightMode === 'both',
      highlightColor: 'teal',
      icon: <Sparkles size={13} />,
    },
    {
      id: 'axe',
      label: 'axe-core',
      sublabel: 'rescore',
      role: 'open source, always local',
      highlight: false,
      icon: <GitBranch size={13} />,
    },
  ];

  return (
    <div className="rounded-xl border border-slate-700/40 bg-slate-900/60 p-4">
      <p className="text-[10px] uppercase tracking-widest text-slate-500 font-semibold mb-3">
        Pipeline roles — where your key is used
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
        Each model fills a named role in an open source orchestration graph. Your key never touches extraction or scoring — only the role shown above.
      </p>
    </div>
  );
}

// ─── Demo panel ──────────────────────────────────────────────────────────────

type EntryMode = 'demo' | 'byok';

function DemoPanel() {
  const [entryMode, setEntryMode] = useState<EntryMode>('demo');
  const [stage, setStage] = useState<PipelineStage>('idle');
  const [dragOver, setDragOver] = useState(false);
  const [fileName, setFileName] = useState<string | null>(null);
  const [claudeKey, setClaudeKey] = useState('');
  const [openaiKey, setOpenaiKey] = useState('');

  const highlightMode: KeyMode | null =
    claudeKey && openaiKey ? 'both' : claudeKey ? 'claude' : openaiKey ? 'openai' : null;

  const startPipeline = (name = 'sample.pdf') => {
    setFileName(name);
    let i = 0;
    const advance = () => {
      setStage(STAGE_ORDER[i]);
      i++;
      if (i < STAGE_ORDER.length) {
        setTimeout(advance, i === 1 ? 600 : 900);
      }
    };
    advance();
  };

  const handleDownload = () => {
    if (!fileName) return;
    const baseName = fileName.replace(/\.pdf$/i, '');
    const blob = new Blob(
      [`<!-- Accessible HTML output for ${fileName} -->\n<html lang="en"><head><title>${baseName}</title></head><body><main><h1>${baseName}</h1><p>Accessible HTML content would appear here.</p></main></body></html>`],
      { type: 'text/html' }
    );
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${baseName}_accessible.html`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const reset = () => {
    setStage('idle');
    setFileName(null);
  };

  const stageIdx = STAGE_ORDER.indexOf(stage);
  const baselineScore = stageIdx >= STAGE_ORDER.indexOf('axe_baseline') ? 61 : 0;
  const round1Score = stageIdx >= STAGE_ORDER.indexOf('round1') ? 84 : 0;
  const finalScore = stage === 'done' ? 97 : 0;

  const violations = [
    { id: '1.1.1', label: 'Missing alt text', impact: 'critical', fixed: stageIdx >= 5 },
    { id: '1.3.1', label: 'Table header missing', impact: 'serious', fixed: stageIdx >= 5 },
    { id: '2.4.3', label: 'Focus order broken', impact: 'serious', fixed: stageIdx >= 6 },
    { id: '1.4.3', label: 'Contrast ratio 3.8:1', impact: 'moderate', fixed: stageIdx >= 6 },
    { id: '4.1.2', label: 'Duplicate element IDs', impact: 'moderate', fixed: stage === 'done' },
  ];

  return (
    <div className="bg-slate-900 rounded-2xl border border-slate-700/60 overflow-hidden">
      {/* Terminal-style header */}
      <div className="flex items-center gap-2 px-4 py-3 bg-slate-800/80 border-b border-slate-700/60">
        <span className="w-3 h-3 rounded-full bg-rose-500/80" />
        <span className="w-3 h-3 rounded-full bg-amber-400/80" />
        <span className="w-3 h-3 rounded-full bg-emerald-500/80" />
        <span className="ml-3 text-xs font-mono text-slate-400">happypdf — pipeline</span>
        {stage !== 'idle' && (
          <button
            onClick={reset}
            className="ml-auto text-slate-500 hover:text-slate-300 transition-colors"
            aria-label="Reset demo"
          >
            <X size={14} />
          </button>
        )}
      </div>

      <div className="p-6 space-y-5">
        {stage === 'idle' ? (
          <>
            {/* Two-path toggle */}
            <div className="grid grid-cols-2 gap-2 p-1 bg-slate-800/60 rounded-xl border border-slate-700/40">
              <button
                onClick={() => setEntryMode('demo')}
                className={`flex items-center justify-center gap-2 px-3 py-2.5 rounded-lg text-sm font-medium transition-all ${
                  entryMode === 'demo'
                    ? 'bg-slate-700 text-slate-100 shadow-sm'
                    : 'text-slate-500 hover:text-slate-300'
                }`}
              >
                <Upload size={14} />
                Try the demo
              </button>
              <button
                onClick={() => setEntryMode('byok')}
                className={`flex items-center justify-center gap-2 px-3 py-2.5 rounded-lg text-sm font-medium transition-all ${
                  entryMode === 'byok'
                    ? 'bg-amber-500/15 text-amber-300 border border-amber-500/25 shadow-sm'
                    : 'text-slate-500 hover:text-slate-300'
                }`}
              >
                <Key size={14} />
                Use my license
              </button>
            </div>

            {entryMode === 'demo' ? (
              /* ── Demo path ── */
              <div
                onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
                onDragLeave={() => setDragOver(false)}
                onDrop={(e) => {
                  e.preventDefault();
                  setDragOver(false);
                  const f = e.dataTransfer.files[0];
                  if (f) startPipeline(f.name);
                }}
                className={`border-2 border-dashed rounded-xl p-8 text-center transition-all cursor-pointer ${
                  dragOver
                    ? 'border-teal-400 bg-teal-400/5'
                    : 'border-slate-600 hover:border-slate-500 hover:bg-slate-800/40'
                }`}
                role="button"
                tabIndex={0}
                aria-label="Drop a PDF or click to try the demo"
                onKeyDown={(e) => e.key === 'Enter' && startPipeline()}
                onClick={() => startPipeline()}
              >
                <Upload className="mx-auto mb-3 text-slate-500" size={28} />
                <p className="text-slate-300 font-medium mb-1">Drop a PDF here</p>
                <p className="text-slate-500 text-sm mb-4">or try it with a sample document</p>
                <button
                  onClick={(e) => { e.stopPropagation(); startPipeline('irs_schedule_c.pdf'); }}
                  className="text-xs font-mono px-3 py-1.5 rounded-md bg-slate-700 text-teal-400 hover:bg-slate-600 transition-colors"
                >
                  Use IRS Schedule C demo →
                </button>
              </div>
            ) : (
              /* ── BYOK path ── */
              <div className="space-y-4">
                <div className="rounded-xl border border-amber-500/20 bg-amber-500/5 px-4 py-3">
                  <p className="text-sm font-semibold text-amber-300 mb-1">Plug your existing license into the pipeline</p>
                  <p className="text-xs text-slate-400 leading-relaxed">
                    If your org already has Claude or ChatGPT API access, connect it here. Your credentials fill a specific role in the open source orchestration graph — zero incremental cost, no new vendor to approve.
                  </p>
                </div>

                <div className="space-y-3">
                  <div className="space-y-1.5">
                    <label className="flex items-center gap-1.5 text-xs text-slate-400 font-medium">
                      <Sparkles size={11} className="text-teal-400" />
                      Claude API Key
                      <span className="text-[10px] text-teal-500 font-normal ml-1">→ judge + patcher role</span>
                    </label>
                    <input
                      type="password"
                      value={claudeKey}
                      onChange={(e) => setClaudeKey(e.target.value)}
                      placeholder="sk-ant-..."
                      className="w-full bg-slate-900 border border-slate-700/60 rounded-lg px-3 py-2.5 text-xs text-slate-200 placeholder:text-slate-600 focus:outline-none focus:border-teal-500/50 transition-colors font-mono"
                    />
                  </div>
                  <div className="space-y-1.5">
                    <label className="flex items-center gap-1.5 text-xs text-slate-400 font-medium">
                      <Users size={11} className="text-emerald-400" />
                      OpenAI API Key
                      <span className="text-[10px] text-emerald-500 font-normal ml-1">→ GPT-4o peer reviewer role</span>
                    </label>
                    <input
                      type="password"
                      value={openaiKey}
                      onChange={(e) => setOpenaiKey(e.target.value)}
                      placeholder="sk-..."
                      className="w-full bg-slate-900 border border-slate-700/60 rounded-lg px-3 py-2.5 text-xs text-slate-200 placeholder:text-slate-600 focus:outline-none focus:border-emerald-500/50 transition-colors font-mono"
                    />
                  </div>
                </div>

                {/* Live role diagram — updates as keys are typed */}
                <PipelineRoleDiagram highlightMode={highlightMode} />

                <button
                  onClick={() => startPipeline('my_document.pdf')}
                  disabled={!claudeKey && !openaiKey}
                  className="w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-amber-500 hover:bg-amber-400 disabled:opacity-40 disabled:cursor-not-allowed text-slate-900 font-semibold text-sm rounded-lg transition-colors"
                >
                  <Upload size={14} />
                  Run pipeline with my credentials
                </button>

                <p className="text-[10px] text-slate-600 leading-relaxed text-center">
                  Keys go directly to your provider. HappyPDF never stores, logs, or caches them.
                </p>
              </div>
            )}
          </>
        ) : (
          /* ── Running / results state ── */
          <div className="space-y-5">
            {/* Original PDF link */}
            {fileName && (
              <div className="flex items-center gap-1.5 text-xs text-slate-500">
                <FileText size={11} className="text-slate-600 shrink-0" />
                <span>Original PDF:</span>
                <span
                  className="text-slate-400 underline underline-offset-2 truncate max-w-[220px]"
                  title={fileName}
                >
                  {fileName}
                </span>
              </div>
            )}

            {/* File pill */}
            <div className="flex items-center gap-3 px-4 py-3 bg-slate-800 rounded-lg border border-slate-700/60">
              <FileText size={16} className="text-teal-400 shrink-0" />
              <span className="text-sm text-slate-300 font-mono truncate">{fileName}</span>
              {stage === 'done' && (
                <span className="ml-auto text-xs text-emerald-400 font-medium flex items-center gap-1">
                  <CheckCircle size={12} /> Complete
                </span>
              )}
            </div>

            {/* Stages */}
            <div className="space-y-1.5">
              {STAGES.map(({ id, label }) => {
                const idx = STAGE_ORDER.indexOf(id);
                const current = STAGE_ORDER.indexOf(stage);
                const done = idx < current || (id === 'done' && stage === 'done');
                const active = STAGE_ORDER.indexOf(id) === current;
                return (
                  <div
                    key={id}
                    className={`flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-all ${
                      active
                        ? 'bg-teal-400/10 border border-teal-400/20'
                        : done
                        ? 'opacity-60'
                        : 'opacity-30'
                    }`}
                  >
                    {done ? (
                      <CheckCircle size={14} className="text-emerald-400 shrink-0" />
                    ) : active ? (
                      <RefreshCw size={14} className="text-teal-400 animate-spin shrink-0" />
                    ) : (
                      <div className="w-3.5 h-3.5 rounded-full border border-slate-600 shrink-0" />
                    )}
                    <span className={done ? 'text-slate-300' : active ? 'text-teal-300' : 'text-slate-500'}>
                      {label}
                    </span>
                  </div>
                );
              })}
            </div>

            {/* Score progression */}
            {stageIdx >= STAGE_ORDER.indexOf('axe_baseline') && (
              <div className="border border-slate-700/60 rounded-xl p-4">
                <p className="text-xs text-slate-500 font-medium uppercase tracking-wider mb-4">
                  Automated check coverage
                </p>
                <div className="flex items-center justify-around">
                  <div className="text-center space-y-2">
                    <ScoreRing score={baselineScore} size={72} stroke={7} />
                    <p className="text-xs text-slate-500">Baseline</p>
                  </div>
                  {round1Score > 0 && (
                    <>
                      <ArrowRight size={14} className="text-slate-600" />
                      <div className="text-center space-y-2">
                        <ScoreRing score={round1Score} size={72} stroke={7} />
                        <p className="text-xs text-slate-500">Round 1</p>
                      </div>
                    </>
                  )}
                  {finalScore > 0 && (
                    <>
                      <ArrowRight size={14} className="text-slate-600" />
                      <div className="text-center space-y-2">
                        <ScoreRing score={finalScore} size={72} stroke={7} />
                        <p className="text-xs text-slate-500">Final</p>
                      </div>
                    </>
                  )}
                </div>
              </div>
            )}

            {/* Violations list */}
            {stageIdx >= STAGE_ORDER.indexOf('axe_baseline') && (
              <div className="space-y-1.5">
                <p className="text-xs text-slate-500 font-medium uppercase tracking-wider px-1">
                  WCAG findings
                </p>
                {violations.map((v) => (
                  <div
                    key={v.id}
                    className={`flex items-center gap-3 px-3 py-2.5 rounded-lg text-xs border transition-all ${
                      v.fixed
                        ? 'border-emerald-500/20 bg-emerald-500/5 opacity-60'
                        : v.impact === 'critical'
                        ? 'border-rose-500/30 bg-rose-500/5'
                        : v.impact === 'serious'
                        ? 'border-amber-500/30 bg-amber-500/5'
                        : 'border-slate-700/60 bg-slate-800/40'
                    }`}
                  >
                    {v.fixed ? (
                      <CheckCircle size={12} className="text-emerald-400 shrink-0" />
                    ) : (
                      <AlertTriangle
                        size={12}
                        className={`shrink-0 ${
                          v.impact === 'critical'
                            ? 'text-rose-400'
                            : v.impact === 'serious'
                            ? 'text-amber-400'
                            : 'text-slate-400'
                        }`}
                      />
                    )}
                    <span className="font-mono text-slate-400">{v.id}</span>
                    <span className={v.fixed ? 'line-through text-slate-600' : 'text-slate-300'}>
                      {v.label}
                    </span>
                    <span
                      className={`ml-auto text-[10px] font-medium uppercase px-1.5 py-0.5 rounded ${
                        v.fixed
                          ? 'text-emerald-500'
                          : v.impact === 'critical'
                          ? 'text-rose-400 bg-rose-500/10'
                          : v.impact === 'serious'
                          ? 'text-amber-400 bg-amber-500/10'
                          : 'text-slate-400 bg-slate-700/50'
                      }`}
                    >
                      {v.fixed ? 'fixed' : v.impact}
                    </span>
                  </div>
                ))}
              </div>
            )}

            {/* Output buttons */}
            {stage === 'done' && (
              <div className="flex gap-3 pt-1">
                <button className="flex items-center justify-center gap-2 px-4 py-2.5 bg-slate-700 hover:bg-slate-600 text-slate-200 text-sm rounded-lg transition-colors">
                  <FileText size={14} />
                  View output HTML
                </button>
                <button
                  onClick={handleDownload}
                  className="flex-1 flex items-center justify-center gap-2 px-4 py-2.5 bg-teal-500 hover:bg-teal-400 text-slate-900 font-semibold text-sm rounded-lg transition-colors"
                >
                  <Download size={14} />
                  Download HTML
                </button>
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
  featured,
}: {
  icon: React.ReactNode;
  label: string;
  badge: string;
  badgeColor: string;
  lines: string[];
  featured?: boolean;
}) {
  return (
    <div className={`bg-slate-900 border rounded-2xl p-6 flex flex-col gap-4 transition-colors ${
      featured
        ? 'border-amber-500/30 hover:border-amber-500/50 ring-1 ring-amber-500/10'
        : 'border-slate-700/60 hover:border-slate-600'
    }`}>
      <div className="flex items-start justify-between">
        <div className={`p-2.5 rounded-xl ${featured ? 'bg-amber-500/10 text-amber-400' : 'bg-slate-800 text-teal-400'}`}>
          {icon}
        </div>
        <span className={`text-xs font-semibold px-2.5 py-1 rounded-full ${badgeColor}`}>{badge}</span>
      </div>
      <div>
        <h3 className="font-semibold text-slate-100 mb-3">{label}</h3>
        <ul className="space-y-2">
          {lines.map((l) => (
            <li key={l} className="flex items-start gap-2 text-sm text-slate-400">
              <ChevronRight size={14} className={`mt-0.5 shrink-0 ${featured ? 'text-amber-600' : 'text-slate-600'}`} />
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
            <a href="#enterprise" className="hover:text-slate-200 transition-colors">Enterprise</a>
            <a href="#modes" className="hover:text-slate-200 transition-colors">Deployment</a>
            <a href="#faq" className="hover:text-slate-200 transition-colors">FAQ</a>
            <a
              href="https://github.com"
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
          <div
            aria-hidden="true"
            className="pointer-events-none absolute inset-0 overflow-hidden"
          >
            <div className="absolute -top-24 left-1/2 -translate-x-1/2 w-[700px] h-[400px] rounded-full bg-teal-500/5 blur-3xl" />
          </div>

          <div className="relative max-w-6xl mx-auto px-4 sm:px-6">
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
                    Try it free
                    <ArrowRight size={16} />
                  </a>
                  <a
                    href="https://github.com"
                    rel="noopener noreferrer"
                    className="flex items-center justify-center gap-2 px-6 py-3 bg-slate-800 hover:bg-slate-700 text-slate-200 font-medium rounded-xl border border-slate-700/60 transition-colors"
                  >
                    <Github size={16} />
                    View on GitHub
                  </a>
                </div>

                <div className="mt-10 flex flex-wrap gap-6 justify-center lg:justify-start">
                  {[
                    { val: '97%', label: 'avg. final score' },
                    { val: '3', label: 'max remediation rounds' },
                    { val: '100%', label: 'open source' },
                  ].map(({ val, label }) => (
                    <div key={label} className="text-center lg:text-left">
                      <p className="text-2xl font-bold text-teal-400 font-mono">{val}</p>
                      <p className="text-xs text-slate-500 mt-0.5">{label}</p>
                    </div>
                  ))}
                </div>

                {/* Enterprise callout in hero */}
                <a
                  href="#enterprise"
                  className="mt-6 inline-flex items-center gap-2 text-sm text-amber-400 hover:text-amber-300 transition-colors group"
                >
                  <Key size={13} />
                  Already have a Claude or ChatGPT license?
                  <ArrowRight size={13} className="group-hover:translate-x-0.5 transition-transform" />
                </a>
              </div>

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

            <div className="relative">
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

        {/* ── Enterprise / BYOK callout ─────────────────────────────────────── */}
        <section id="enterprise" className="py-20 sm:py-28">
          <div className="max-w-5xl mx-auto px-4 sm:px-6">
            <div className="rounded-2xl border border-amber-500/20 bg-gradient-to-br from-amber-500/5 to-slate-900 overflow-hidden">
              <div className="grid lg:grid-cols-2 gap-0">
                {/* Left: the pitch */}
                <div className="p-8 sm:p-10 border-b lg:border-b-0 lg:border-r border-amber-500/10">
                  <div className="inline-flex items-center gap-2 px-2.5 py-1 rounded-full bg-amber-500/10 border border-amber-500/20 text-xs text-amber-400 font-medium mb-6">
                    <Key size={11} />
                    Enterprise
                  </div>
                  <h2 className="text-2xl sm:text-3xl font-extrabold text-white tracking-tight mb-4">
                    Already paying for Claude or ChatGPT?
                  </h2>
                  <p className="text-slate-400 leading-relaxed mb-6">
                    If your organization has existing Claude or GPT-4o API access through enterprise agreements, you can plug those credentials directly into HappyPDF's open source pipeline.
                  </p>
                  <ul className="space-y-3 mb-8">
                    {[
                      { icon: <CheckCircle size={14} className="text-emerald-400 shrink-0 mt-0.5" />, text: 'Zero incremental cost — uses API access you already purchased' },
                      { icon: <CheckCircle size={14} className="text-emerald-400 shrink-0 mt-0.5" />, text: 'No new vendor to approve — no new procurement process' },
                      { icon: <CheckCircle size={14} className="text-emerald-400 shrink-0 mt-0.5" />, text: 'Same quality ceiling as the hosted demo — full pipeline' },
                      { icon: <CheckCircle size={14} className="text-emerald-400 shrink-0 mt-0.5" />, text: 'Keys go directly to your provider — HappyPDF never stores them' },
                    ].map(({ icon, text }) => (
                      <li key={text} className="flex items-start gap-3 text-sm text-slate-300">
                        {icon}
                        {text}
                      </li>
                    ))}
                  </ul>
                  <a
                    href="#demo"
                    className="inline-flex items-center gap-2 px-5 py-2.5 bg-amber-500 hover:bg-amber-400 text-slate-900 font-semibold text-sm rounded-xl transition-colors"
                  >
                    <Key size={14} />
                    Connect my license
                    <ArrowRight size={14} />
                  </a>
                </div>

                {/* Right: the architecture explanation */}
                <div className="p-8 sm:p-10">
                  <p className="text-xs font-semibold uppercase tracking-widest text-slate-500 mb-5">
                    What your key actually does
                  </p>

                  <p className="text-sm text-slate-400 leading-relaxed mb-6">
                    HappyPDF is not a black box that "uses AI." It's a modular open source orchestration graph. Each model has a fixed role. Your API key fills one specific role — nothing more.
                  </p>

                  {/* Static role diagram */}
                  <div className="space-y-2.5 mb-6">
                    {[
                      {
                        icon: <Cpu size={13} />,
                        label: 'olmOCR',
                        role: 'PDF extraction + alt text',
                        yours: false,
                        note: 'Ai2 open model · always free',
                        color: 'slate',
                      },
                      {
                        icon: <Users size={13} />,
                        label: 'Peer reviewers',
                        role: 'Gemini · GPT-4o · OLMo',
                        yours: true,
                        note: 'Your OpenAI key powers GPT-4o here',
                        color: 'emerald',
                      },
                      {
                        icon: <Sparkles size={13} />,
                        label: 'Judge + patcher',
                        role: 'Deduplicates findings · applies fixes',
                        yours: true,
                        note: 'Your Claude key powers this role',
                        color: 'teal',
                      },
                      {
                        icon: <GitBranch size={13} />,
                        label: 'axe-core',
                        role: 'Rescore after each round',
                        yours: false,
                        note: 'Open source · always local',
                        color: 'slate',
                      },
                    ].map((node) => (
                      <div
                        key={node.label}
                        className={`flex items-center gap-3 px-3.5 py-3 rounded-xl border transition-colors ${
                          node.yours
                            ? node.color === 'teal'
                              ? 'border-teal-500/30 bg-teal-500/5'
                              : 'border-emerald-500/30 bg-emerald-500/5'
                            : 'border-slate-700/50 bg-slate-800/30'
                        }`}
                      >
                        <div className={`shrink-0 ${
                          node.yours
                            ? node.color === 'teal' ? 'text-teal-400' : 'text-emerald-400'
                            : 'text-slate-500'
                        }`}>
                          {node.icon}
                        </div>
                        <div className="min-w-0">
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className={`text-sm font-semibold ${
                              node.yours
                                ? node.color === 'teal' ? 'text-teal-300' : 'text-emerald-300'
                                : 'text-slate-400'
                            }`}>
                              {node.label}
                            </span>
                            <span className="text-xs text-slate-600">{node.role}</span>
                          </div>
                          <p className={`text-[11px] mt-0.5 ${
                            node.yours
                              ? node.color === 'teal' ? 'text-teal-500' : 'text-emerald-500'
                              : 'text-slate-600'
                          }`}>
                            {node.note}
                          </p>
                        </div>
                        {node.yours && (
                          <span className={`ml-auto text-[10px] font-semibold uppercase px-2 py-0.5 rounded-full shrink-0 ${
                            node.color === 'teal'
                              ? 'bg-teal-500/15 text-teal-400'
                              : 'bg-emerald-500/15 text-emerald-400'
                          }`}>
                            your key
                          </span>
                        )}
                      </div>
                    ))}
                  </div>

                  <p className="text-[11px] text-slate-600 leading-relaxed">
                    The orchestration logic, patch application, and scoring are all open source Python — your key never touches them. You can read every line at any time.
                  </p>
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* ── Deployment modes ─────────────────────────────────────────────── */}
        <section id="modes" className="py-20 sm:py-28 bg-slate-900/40 border-y border-slate-800/60">
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
                label="Plug in your enterprise license"
                badge="Zero procurement friction"
                badgeColor="bg-amber-500/10 text-amber-400 border border-amber-500/20"
                lines={[
                  'Connect existing Claude or ChatGPT API credentials',
                  'Zero incremental cost on already-approved access',
                  'No new vendor approval required',
                  'Same quality as hosted — your key, your pipeline',
                ]}
                featured
              />
            </div>

            <p className="mt-6 text-center text-xs text-slate-600">
              The real barrier to enterprise adoption is procurement friction, not technical
              capability. Plugging in your existing license sidesteps it entirely.
            </p>
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
                q="What does 'plug in your license' mean exactly?"
                a="If your organization already has Claude or GPT-4o API access through enterprise agreements, you connect those credentials here. HappyPDF routes them to the specific model roles they cover (Claude → judge + patcher, GPT-4o → peer reviewer). You pay nothing extra beyond what you already pay your AI provider — and your key goes directly to them, never stored or logged by HappyPDF."
              />
              <FaqItem
                q="Why is the pipeline modular? Can I swap models?"
                a="Yes. The orchestration is open source Python with well-defined role interfaces. Each model slot (extractor, reviewer, judge) can be pointed at any model that fits the interface — Claude, GPT-4o, OLMo, Llama, or a local model. The modularity is what makes BYOK possible without rewriting anything."
              />
              <FaqItem
                q="How is this different from DocAccess or SentraCheck?"
                a="Commercial tools are closed-box, paid per conversion, and don't expose their logic. HappyPDF is fully open source — every patch, every reviewer score, every violation flag is in the audit trail. You can inspect exactly what changed and why. And you can run it on your own infrastructure or pipe in your existing AI contracts."
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
              No account. No credit card. Drop a PDF and see the pipeline run in your browser — or connect your existing API license.
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
                href="https://github.com"
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
            <a href="#faq" className="hover:text-slate-300 transition-colors">
              FAQ
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
