"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

type ProjectConfig = {
  market: string;
  episode_count: number;
  episode_duration_seconds: number;
  first_paywall_episode: number;
  budget_level: string;
  max_iteration_budget: number | null;
};

type Project = {
  id: string;
  title: string;
  idea: string;
  config: ProjectConfig;
  status: string;
  iteration: number;
  current_version_id: string | null;
  human_review_token: string | null;
  updated_at: string;
};

type Episode = {
  episode: number;
  title: string;
  screenplay: string;
  ending_hook: string;
};

type Finding = {
  reviewer: string;
  severity: "S" | "A" | "B";
  episode_refs: number[];
  evidence: string;
  judgment: string;
  audience_risk: string;
};

type Review = { reviewer: string; score: number; findings: Finding[] };

type Version = {
  id: string;
  version_number: number;
  iteration: number;
  created_at: string;
  script: {
    title: string;
    logline: string;
    story_bible: Record<string, unknown>;
    character_bible: Array<Record<string, string>>;
    episodes: Episode[];
  };
  reviews: Review[];
  verification: Review;
  revision_brief: Record<string, unknown> | null;
};

type Comment = {
  id: string;
  episode_id: number;
  anchor: string | null;
  body: string;
  created_at: string;
};

type ModelSettings = {
  provider: "mock" | "openai-compatible";
  base_url: string;
  has_api_key: boolean;
  default_model: string;
  writer_model: string;
  reviewer_model: string;
  editor_model: string;
  timeout_seconds: number;
};

async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: { "Content-Type": "application/json", ...options?.headers },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: "请求失败" }));
    throw new Error(body.detail || `请求失败 (${response.status})`);
  }
  return response.json();
}

function statusLabel(status: string) {
  return {
    DRAFT: "等待生成",
    GENERATING: "正在创作",
    REVIEWING: "AI 审查中",
    WAITING_HUMAN_REVIEW: "等待人工审阅",
    HUMAN_DECISION_REQUIRED: "需要人工决定",
    FINAL: "已定稿",
    FAILED: "生成失败",
  }[status] || status;
}

export default function Home() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [project, setProject] = useState<Project | null>(null);
  const [versions, setVersions] = useState<Version[]>([]);
  const [selectedVersion, setSelectedVersion] = useState<Version | null>(null);
  const [episodeNumber, setEpisodeNumber] = useState(1);
  const [comments, setComments] = useState<Comment[]>([]);
  const [tab, setTab] = useState<"episodes" | "review" | "story" | "characters" | "versions">("episodes");
  const [createOpen, setCreateOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [modelSettings, setModelSettings] = useState<ModelSettings | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [commentBody, setCommentBody] = useState("");
  const [commentAnchor, setCommentAnchor] = useState("");
  const [noChanges, setNoChanges] = useState(false);

  const loadProjects = useCallback(async () => {
    const list = await api<Project[]>("/projects");
    setProjects(list);
    return list;
  }, []);

  const loadProject = useCallback(async (projectId: string) => {
    const [nextProject, nextVersions] = await Promise.all([
      api<Project>(`/projects/${projectId}`),
      api<Version[]>(`/projects/${projectId}/versions`),
    ]);
    setProject(nextProject);
    setVersions(nextVersions);
    const current = nextVersions.find((version) => version.id === nextProject.current_version_id) || nextVersions.at(-1) || null;
    setSelectedVersion(current);
    if (current) {
      setEpisodeNumber(current.script.episodes[0]?.episode || 1);
      const openComments = await api<Comment[]>(`/projects/${projectId}/comments?version_id=${current.id}`);
      setComments(openComments);
    } else {
      setComments([]);
    }
  }, []);

  useEffect(() => {
    Promise.all([loadProjects(), api<ModelSettings>("/settings/model")])
      .then(([list, settings]) => {
        setModelSettings(settings);
        if (list[0]) return loadProject(list[0].id);
      })
      .catch((reason) => setError(reason.message));
  }, [loadProject, loadProjects]);

  const currentEpisode = selectedVersion?.script.episodes.find((item) => item.episode === episodeNumber);
  const episodeComments = comments.filter((item) => item.episode_id === episodeNumber);
  const allReviews = selectedVersion ? [...selectedVersion.reviews, selectedVersion.verification] : [];
  const overallScore = allReviews.length
    ? allReviews.reduce((sum, item) => sum + item.score, 0) / allReviews.length
    : 0;
  const findings = allReviews.flatMap((item) => item.findings);
  const severityCounts = useMemo(
    () => ({
      S: findings.filter((item) => item.severity === "S").length,
      A: findings.filter((item) => item.severity === "A").length,
      B: findings.filter((item) => item.severity === "B").length,
    }),
    [findings],
  );

  async function runAction(action: () => Promise<unknown>) {
    setBusy(true);
    setError("");
    try {
      await action();
      if (project) {
        await Promise.all([loadProject(project.id), loadProjects()]);
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "操作失败");
    } finally {
      setBusy(false);
    }
  }

  async function addComment(event: FormEvent) {
    event.preventDefault();
    if (!project || !commentBody.trim()) return;
    await runAction(async () => {
      await api(`/projects/${project.id}/comments`, {
        method: "POST",
        body: JSON.stringify({
          episode_id: episodeNumber,
          body: commentBody.trim(),
          anchor: commentAnchor.trim() || null,
        }),
      });
      setCommentBody("");
      setCommentAnchor("");
    });
  }

  async function generateNext() {
    if (!project?.human_review_token) return;
    await runAction(() =>
      api(`/projects/${project.id}/review/generate`, {
        method: "POST",
        body: JSON.stringify({
          review_token: project.human_review_token,
          no_changes_confirmed: comments.length === 0 && noChanges,
        }),
      }),
    );
    setNoChanges(false);
  }

  async function finalize() {
    if (!project?.human_review_token || !window.confirm("确认将当前版本批准为最终稿？")) return;
    await runAction(() =>
      api(`/projects/${project.id}/review/finalize`, {
        method: "POST",
        body: JSON.stringify({ review_token: project.human_review_token }),
      }),
    );
  }

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">幕</div>
          <div><strong>Scriptroom</strong><span>AI 编剧工作台</span></div>
        </div>
        <button className="new-project" onClick={() => setCreateOpen(true)}><span>＋</span> 新建剧本</button>
        <div className="sidebar-label">项目</div>
        <nav className="project-list" aria-label="项目列表">
          {projects.map((item) => (
            <button
              key={item.id}
              className={project?.id === item.id ? "project-link active" : "project-link"}
              onClick={() => loadProject(item.id).catch((reason) => setError(reason.message))}
            >
              <span className="project-glyph">{item.title.slice(0, 1)}</span>
              <span><strong>{item.title}</strong><small>第 {item.iteration || 0} 轮 · {statusLabel(item.status)}</small></span>
            </button>
          ))}
          {!projects.length && <p className="empty-sidebar">还没有项目，从一个故事灵感开始。</p>}
        </nav>
        <button className="settings-link" onClick={() => setSettingsOpen(true)}>
          <span>⚙</span><span><strong>模型设置</strong><small>{modelSettings?.provider === "mock" ? "Mock 模式" : modelSettings?.writer_model}</small></span>
        </button>
      </aside>

      <section className="workspace">
        {error && <div className="error-banner"><span>!</span>{error}<button onClick={() => setError("")}>×</button></div>}
        {!project ? (
          <EmptyState onCreate={() => setCreateOpen(true)} onSettings={() => setSettingsOpen(true)} />
        ) : (
          <>
            <header className="topbar">
              <div>
                <div className="eyebrow">{project.config.market} · {project.config.episode_count} 集 · {Math.round(project.config.episode_duration_seconds / 60)} 分钟/集</div>
                <h1>{project.title}</h1>
              </div>
              <div className="topbar-actions">
                <span className={`status status-${project.status.toLowerCase()}`}><i />{statusLabel(project.status)}</span>
                <button className="icon-button" onClick={() => setSettingsOpen(true)} aria-label="打开模型设置">⚙</button>
              </div>
            </header>

            <div className="workflow-strip">
              <div className={project.iteration ? "flow-step done" : "flow-step active"}><b>1</b><span>创作简报</span></div>
              <i />
              <div className={project.status === "GENERATING" ? "flow-step active" : project.iteration ? "flow-step done" : "flow-step"}><b>2</b><span>剧本生成</span></div>
              <i />
              <div className={project.status === "REVIEWING" ? "flow-step active" : project.iteration ? "flow-step done" : "flow-step"}><b>3</b><span>AI 审查</span></div>
              <i />
              <div className={project.status.includes("HUMAN") || project.status === "WAITING_HUMAN_REVIEW" ? "flow-step active" : project.status === "FINAL" ? "flow-step done" : "flow-step"}><b>4</b><span>人工审阅</span></div>
              <i />
              <div className={project.status === "FINAL" ? "flow-step done" : "flow-step"}><b>5</b><span>定稿</span></div>
            </div>

            {!selectedVersion ? (
              <DraftStart project={project} busy={busy} onGenerate={() => runAction(() => api(`/projects/${project.id}/iterations`, { method: "POST" }))} />
            ) : (
              <>
                <div className="tabs">
                  {([
                    ["episodes", "分集剧本"], ["review", "AI 审查"], ["story", "故事设定"],
                    ["characters", "人物"], ["versions", "版本"],
                  ] as const).map(([key, label]) => (
                    <button key={key} className={tab === key ? "active" : ""} onClick={() => setTab(key)}>{label}</button>
                  ))}
                </div>

                {tab === "episodes" && (
                  <div className="review-layout">
                    <aside className="episode-rail">
                      <div className="rail-heading"><span>分集</span><small>{selectedVersion.script.episodes.length} 集</small></div>
                      {selectedVersion.script.episodes.map((episode) => {
                        const count = comments.filter((item) => item.episode_id === episode.episode).length;
                        return <button key={episode.episode} className={episodeNumber === episode.episode ? "active" : ""} onClick={() => setEpisodeNumber(episode.episode)}>
                          <span>EP {String(episode.episode).padStart(2, "0")}</span>{count > 0 && <em>{count}</em>}
                        </button>;
                      })}
                    </aside>
                    <article className="script-panel">
                      <div className="script-toolbar">
                        <div><span>当前版本</span><strong>V{selectedVersion.version_number}</strong></div>
                        <div><span>集尾钩子</span><strong>{currentEpisode?.ending_hook || "—"}</strong></div>
                      </div>
                      <div className="script-page">
                        <div className="episode-kicker">EPISODE {String(episodeNumber).padStart(2, "0")}</div>
                        <h2>{currentEpisode?.title}</h2>
                        <pre>{currentEpisode?.screenplay}</pre>
                      </div>
                    </article>
                    <aside className="comments-panel">
                      <div className="comments-heading"><div><span>人工批注</span><small>{episodeComments.length} 条意见</small></div><b>EP {String(episodeNumber).padStart(2, "0")}</b></div>
                      <div className="comment-list">
                        {episodeComments.map((comment, index) => <div className="comment-card" key={comment.id}>
                          <div><span>{index + 1}</span><small>{comment.anchor || "整集意见"}</small></div>
                          <p>{comment.body}</p>
                        </div>)}
                        {!episodeComments.length && <div className="comment-empty"><span>✎</span><p>审阅这集后，在下方留下修改意见。</p></div>}
                      </div>
                      {project.status === "WAITING_HUMAN_REVIEW" && selectedVersion.id === project.current_version_id && <form className="comment-form" onSubmit={addComment}>
                        <input value={commentAnchor} onChange={(event) => setCommentAnchor(event.target.value)} placeholder="定位，如：1-2 场 / 集尾" />
                        <textarea value={commentBody} onChange={(event) => setCommentBody(event.target.value)} placeholder="写下具体、可执行的修改意见…" rows={4} />
                        <button disabled={busy || !commentBody.trim()}>添加批注</button>
                      </form>}
                    </aside>
                  </div>
                )}

                {tab === "review" && <ReviewPanel score={overallScore} counts={severityCounts} reviews={allReviews} findings={findings} />}
                {tab === "story" && <StoryPanel version={selectedVersion} />}
                {tab === "characters" && <CharactersPanel version={selectedVersion} />}
                {tab === "versions" && <VersionsPanel versions={versions} selected={selectedVersion} onSelect={setSelectedVersion} />}

                {project.status === "WAITING_HUMAN_REVIEW" && selectedVersion.id === project.current_version_id && <div className="action-dock">
                  <div>
                    <span>第 {project.iteration} 轮已完成</span>
                    <strong>{comments.length ? `已记录 ${comments.length} 条人工意见` : "等待你的审阅决定"}</strong>
                  </div>
                  {!comments.length && <label className="no-change"><input type="checkbox" checked={noChanges} onChange={(event) => setNoChanges(event.target.checked)} />本轮无需修改</label>}
                  <button className="secondary" onClick={finalize} disabled={busy}>批准并定稿</button>
                  <button className="primary" onClick={generateNext} disabled={busy || (!comments.length && !noChanges)}>{busy ? "处理中…" : `Generate 第 ${project.iteration + 1} 轮 →`}</button>
                </div>}
              </>
            )}
          </>
        )}
      </section>

      {createOpen && <CreateProjectModal onClose={() => setCreateOpen(false)} onCreated={async (created) => {
        setCreateOpen(false); await loadProjects(); await loadProject(created.id);
      }} />}
      {settingsOpen && modelSettings && <SettingsModal settings={modelSettings} onClose={() => setSettingsOpen(false)} onSaved={(next) => { setModelSettings(next); setSettingsOpen(false); }} />}
      {busy && <div className="busy-overlay"><div className="loader" /><strong>智能体正在工作</strong><span>生成与并行审查可能需要几分钟，请不要关闭页面。</span></div>}
    </main>
  );
}

function EmptyState({ onCreate, onSettings }: { onCreate: () => void; onSettings: () => void }) {
  return <div className="empty-state"><div className="empty-wordmark">SCRIPTROOM</div><div className="empty-orbit"><span>✦</span></div><p className="eyebrow">HUMAN × AI STORY DEVELOPMENT</p><h1>从一个灵感，<br />到一部可以审阅的剧本。</h1><p>多智能体完成创作与审查，你保留每一轮的最终决定权。</p><div><button className="primary" onClick={onCreate}>创建第一个项目 →</button><button className="text-button" onClick={onSettings}>先配置真实模型</button></div></div>;
}

function DraftStart({ project, busy, onGenerate }: { project: Project; busy: boolean; onGenerate: () => void }) {
  return <div className="draft-start"><div className="brief-card"><span className="eyebrow">CREATIVE INPUT</span><h2>准备生成第一版</h2><blockquote>{project.idea}</blockquote><div className="brief-grid"><span><small>目标市场</small>{project.config.market}</span><span><small>剧集规模</small>{project.config.episode_count} 集</span><span><small>首个付费点</small>EP {project.config.first_paywall_episode}</span><span><small>制作预算</small>{project.config.budget_level}</span></div><button className="primary" onClick={onGenerate} disabled={busy}>Generate 第一版 →</button></div></div>;
}

function ReviewPanel({ score, counts, reviews, findings }: { score: number; counts: Record<string, number>; reviews: Review[]; findings: Finding[] }) {
  return <div className="content-view"><div className="review-hero"><div className="score-ring"><strong>{score.toFixed(1)}</strong><span>/ 10</span></div><div><span className="eyebrow">OVERALL REVIEW</span><h2>AI 联合审查报告</h2><p>先看剧本证据，再看判断。评分只辅助你的人工决策。</p></div><div className="severity-summary"><span className="sev-s">S 级 <b>{counts.S}</b></span><span className="sev-a">A 级 <b>{counts.A}</b></span><span className="sev-b">B 级 <b>{counts.B}</b></span></div></div><div className="reviewer-scores">{reviews.map((review) => <div key={review.reviewer}><span>{review.reviewer}</span><strong>{review.score.toFixed(1)}</strong></div>)}</div><div className="finding-grid">{findings.map((finding, index) => <article key={`${finding.reviewer}-${index}`}><header><span className={`severity severity-${finding.severity.toLowerCase()}`}>{finding.severity}</span><small>{finding.reviewer} · EP {finding.episode_refs.join(", ")}</small></header><h3>{finding.judgment}</h3><dl><dt>剧本证据</dt><dd>{finding.evidence}</dd><dt>观众风险</dt><dd>{finding.audience_risk}</dd></dl></article>)}</div></div>;
}

function StoryPanel({ version }: { version: Version }) {
  return <div className="content-view"><div className="section-heading"><span className="eyebrow">STORY BIBLE</span><h2>{version.script.logline}</h2></div><div className="data-grid">{Object.entries(version.script.story_bible).map(([key, value]) => <div key={key}><small>{key.replaceAll("_", " ")}</small><p>{Array.isArray(value) ? value.join("；") : String(value)}</p></div>)}</div></div>;
}

function CharactersPanel({ version }: { version: Version }) {
  return <div className="content-view"><div className="section-heading"><span className="eyebrow">CHARACTER BIBLE</span><h2>人物与剧情功能</h2></div><div className="character-grid">{version.script.character_bible.map((character, index) => <article key={index}><div className="character-avatar">{String(character.name || "角").slice(0, 1)}</div><h3>{character.name}</h3><span>{character.identity}</span><dl>{Object.entries(character).filter(([key]) => !["name", "identity"].includes(key)).map(([key, value]) => <div key={key}><dt>{key.replaceAll("_", " ")}</dt><dd>{value}</dd></div>)}</dl></article>)}</div></div>;
}

function VersionsPanel({ versions, selected, onSelect }: { versions: Version[]; selected: Version; onSelect: (version: Version) => void }) {
  return <div className="content-view"><div className="section-heading"><span className="eyebrow">VERSION HISTORY</span><h2>每一轮都有迹可循</h2><p>选择旧版本后可切换到其他标签查看，旧版本保持只读。</p></div><div className="version-list">{[...versions].reverse().map((version) => <button className={selected.id === version.id ? "active" : ""} key={version.id} onClick={() => onSelect(version)}><b>V{version.version_number}</b><span><strong>Iteration {version.iteration}</strong><small>{new Date(version.created_at).toLocaleString("zh-CN")}</small></span><em>{version.script.episodes.length} 集</em></button>)}</div></div>;
}

function CreateProjectModal({ onClose, onCreated }: { onClose: () => void; onCreated: (project: Project) => void }) {
  const [saving, setSaving] = useState(false); const [error, setError] = useState("");
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setSaving(true); setError("");
    const values = new FormData(event.currentTarget);
    try { const created = await api<Project>("/projects", { method: "POST", body: JSON.stringify({ title: values.get("title"), idea: values.get("idea"), config: { market: values.get("market"), episode_count: Number(values.get("episodes")), episode_duration_seconds: Number(values.get("duration")) * 60, first_paywall_episode: Number(values.get("paywall")), budget_level: values.get("budget"), max_iteration_budget: values.get("maxIterations") ? Number(values.get("maxIterations")) : null } }) }); onCreated(created); } catch (reason) { setError(reason instanceof Error ? reason.message : "创建失败"); } finally { setSaving(false); }
  }
  return <div className="modal-backdrop"><div className="modal modal-wide"><button className="modal-close" onClick={onClose}>×</button><span className="eyebrow">NEW STORY PROJECT</span><h2>创建剧本项目</h2><p>先定义创作边界，Agent 会据此生成第一版。</p>{error && <div className="form-error">{error}</div>}<form onSubmit={submit}><label className="full">项目名称<input name="title" required placeholder="例如：失控继承人" /></label><label className="full">一句话灵感<textarea name="idea" required rows={5} placeholder="一个怎样的人，因为怎样的事件，被迫做什么？" /></label><label>目标市场<select name="market" defaultValue="欧美"><option>欧美</option><option>中国大陆</option><option>东南亚</option><option>日韩</option></select></label><label>集数<input name="episodes" type="number" min="1" max="200" defaultValue="60" /></label><label>单集时长（分钟）<input name="duration" type="number" min="1" max="30" defaultValue="2" /></label><label>首个付费点<input name="paywall" type="number" min="1" defaultValue="10" /></label><label>制作预算<select name="budget" defaultValue="中等"><option>低</option><option>中等</option><option>高</option></select></label><label>最大迭代预算<input name="maxIterations" type="number" min="1" placeholder="不限制" /></label><div className="form-actions full"><button type="button" className="secondary" onClick={onClose}>取消</button><button className="primary" disabled={saving}>{saving ? "创建中…" : "创建项目 →"}</button></div></form></div></div>;
}

function SettingsModal({ settings, onClose, onSaved }: { settings: ModelSettings; onClose: () => void; onSaved: (settings: ModelSettings) => void }) {
  const [provider, setProvider] = useState(settings.provider); const [saving, setSaving] = useState(false); const [error, setError] = useState("");
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setSaving(true); setError(""); const values = new FormData(event.currentTarget);
    try { const next = await api<ModelSettings>("/settings/model", { method: "PUT", body: JSON.stringify({ provider, base_url: values.get("baseUrl"), api_key: values.get("apiKey") || null, default_model: values.get("defaultModel"), writer_model: values.get("writerModel"), reviewer_model: values.get("reviewerModel"), editor_model: values.get("editorModel"), timeout_seconds: Number(values.get("timeout")) }) }); onSaved(next); } catch (reason) { setError(reason instanceof Error ? reason.message : "保存失败"); } finally { setSaving(false); }
  }
  return <div className="modal-backdrop"><div className="modal settings-modal"><button className="modal-close" onClick={onClose}>×</button><span className="eyebrow">MODEL CONNECTION</span><h2>大语言模型设置</h2><p>保存后从下一次生成开始生效，不需要重启后端。</p><div className="provider-switch"><button className={provider === "mock" ? "active" : ""} onClick={() => setProvider("mock")}><b>Mock</b><span>本地测试，无费用</span></button><button className={provider === "openai-compatible" ? "active" : ""} onClick={() => setProvider("openai-compatible")}><b>真实模型</b><span>OpenAI 兼容接口</span></button></div>{error && <div className="form-error">{error}</div>}<form onSubmit={submit}><label className="full">API Base URL<input name="baseUrl" defaultValue={settings.base_url} disabled={provider === "mock"} /></label><label className="full">API Key<input name="apiKey" type="password" disabled={provider === "mock"} placeholder={settings.has_api_key ? "已保存；留空保持不变" : "sk-…"} /></label><div className="model-role"><span>Agent 角色</span><span>模型 ID</span></div><label className="role-row"><span><b>Story Writer</b><small>唯一创作 Agent</small></span><input name="writerModel" defaultValue={settings.writer_model} /></label><label className="role-row"><span><b>Reviewers</b><small>五路并行审查</small></span><input name="reviewerModel" defaultValue={settings.reviewer_model} /></label><label className="role-row"><span><b>Chief Editor</b><small>整合人工意见</small></span><input name="editorModel" defaultValue={settings.editor_model} /></label><label className="role-row"><span><b>Default</b><small>Brief 等通用任务</small></span><input name="defaultModel" defaultValue={settings.default_model} /></label><label className="timeout-label">单次超时（秒）<input name="timeout" type="number" min="10" max="900" defaultValue={settings.timeout_seconds} /></label><div className="settings-note"><span>🔒</span><p>API Key 保存在本机 SQLite，不会在页面或接口中回显。生产环境建议迁移到密钥管理服务。</p></div><div className="form-actions"><button type="button" className="secondary" onClick={onClose}>取消</button><button className="primary" disabled={saving}>{saving ? "保存中…" : "保存并应用"}</button></div></form></div></div>;
}
