import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { getPresets, createPreset, deletePreset, generateTopics, runFirstPass, completeOnboarding } from "../api";
import { useUser } from "../UserContext";
import PaperCard from "../components/PaperCard";
import styles from "./Onboarding.module.css";

const TOTAL_STEPS = 3;

function StepIndicator({ step }) {
  return (
    <div className={styles.stepIndicator}>
      {Array.from({ length: TOTAL_STEPS }, (_, i) => (
        <div key={i} className={styles.dot} data-active={i < step} />
      ))}
    </div>
  );
}

function TagEditor({ tags, onChange, type = "include" }) {
  const [input, setInput] = useState("");

  function handleKeyDown(e) {
    if (e.key === "Enter" && input.trim()) {
      e.preventDefault();
      onChange([...tags, input.trim()]);
      setInput("");
    }
  }

  function handleRemove(idx) {
    onChange(tags.filter((_, i) => i !== idx));
  }

  return (
    <div className={styles.tags}>
      {tags.map((tag, i) => (
        <span key={i} className={styles.tag} data-type={type}>
          {tag}
          <button className={styles.tagRemove} onClick={() => handleRemove(i)}>
            x
          </button>
        </span>
      ))}
      <input
        className={styles.tagInput}
        placeholder="Add term..."
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={handleKeyDown}
      />
    </div>
  );
}

// ── Preset Creator Form ──

function PresetCreator({ onSave, onCancel }) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [includeAny, setIncludeAny] = useState([]);
  const [includeAll, setIncludeAll] = useState([]);
  const [exclude, setExclude] = useState([]);
  const [saving, setSaving] = useState(false);

  async function handleSave() {
    if (!name.trim() || includeAny.length === 0) return;
    setSaving(true);
    try {
      await onSave({ name, description, include_any: includeAny, include_all: includeAll, exclude });
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className={styles.presetCreator}>
      <h3 className={styles.presetCreatorTitle}>Create custom preset</h3>
      <div className={styles.fieldGroup}>
        <label className={styles.label}>Name</label>
        <input
          className={styles.input}
          placeholder="e.g. spinal-cord-mri"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
      </div>
      <div className={styles.fieldGroup}>
        <label className={styles.label}>Description</label>
        <input
          className={styles.input}
          placeholder="Short description of what this preset tracks"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
      </div>
      <div className={styles.tagSection}>
        <div className={styles.tagLabel}>Related terms (any match)</div>
        <TagEditor tags={includeAny} onChange={setIncludeAny} />
      </div>
      <div className={styles.tagSection}>
        <div className={styles.tagLabel}>Must contain (all required)</div>
        <TagEditor tags={includeAll} onChange={setIncludeAll} type="required" />
      </div>
      <div className={styles.tagSection}>
        <div className={styles.tagLabel}>Exclude</div>
        <TagEditor tags={exclude} onChange={setExclude} type="exclude" />
      </div>
      <div className={styles.presetCreatorActions}>
        <button className={styles.secondaryBtn} onClick={onCancel}>Cancel</button>
        <button
          className={styles.secondaryBtn}
          onClick={handleSave}
          disabled={saving || !name.trim() || includeAny.length === 0}
          style={{ background: "var(--color-accent)", color: "white", borderColor: "var(--color-accent)" }}
        >
          {saving ? "Saving..." : "Save preset"}
        </button>
      </div>
    </div>
  );
}

// ── Step 1: Welcome ──

function StepWelcome({ onNext }) {
  const [presets, setPresets] = useState([]);
  const [selectedPresets, setSelectedPresets] = useState(new Set());
  const [mode, setMode] = useState(null); // null | "presets" | "describe"
  const [description, setDescription] = useState("");
  const [abstracts, setAbstracts] = useState([]);
  const [showAbstracts, setShowAbstracts] = useState(false);
  const [showCreator, setShowCreator] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    loadPresets();
  }, []);

  function loadPresets() {
    getPresets()
      .then((data) => setPresets(data.presets || []))
      .catch(() => {});
  }

  function togglePreset(name) {
    setSelectedPresets((prev) => {
      const next = new Set(prev);
      if (next.has(name)) {
        next.delete(name);
      } else {
        next.add(name);
      }
      return next;
    });
  }

  async function handleCreatePreset(data) {
    await createPreset(data);
    setShowCreator(false);
    loadPresets();
  }

  async function handleDeletePreset(e, presetId) {
    e.stopPropagation();
    await deletePreset(presetId);
    loadPresets();
  }

  function handleUsePresets() {
    if (selectedPresets.size === 0) return;
    const topics = presets
      .filter((p) => selectedPresets.has(p.name))
      .map(({ description: _, id: _id, created_by: _cb, ...rest }) => rest);
    onNext({
      topics,
      description: "",
      seedAbstracts: [],
    });
  }

  async function handleGenerate() {
    if (!description.trim()) return;
    setLoading(true);
    setError("");
    try {
      const data = await generateTopics(description, abstracts.filter(Boolean));
      onNext({
        topics: data.topics,
        description,
        seedAbstracts: abstracts.filter(Boolean),
      });
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <h1 className={styles.title}>Set up your research feed</h1>
      <p className={styles.subtitle}>
        Pick from ready-made topic presets or describe your research to generate custom ones.
      </p>

      {/* Mode selector */}
      <div className={styles.modeSelector}>
        <button
          className={styles.modeBtn}
          data-active={mode === "presets"}
          onClick={() => setMode("presets")}
        >
          <span className={styles.modeBtnTitle}>Choose from presets</span>
          <span className={styles.modeBtnHint}>
            Pick from curated keyword sets. Best if your field is already listed.
          </span>
        </button>
        <button
          className={styles.modeBtn}
          data-active={mode === "describe"}
          onClick={() => setMode("describe")}
        >
          <span className={styles.modeBtnTitle}>Describe my research</span>
          <span className={styles.modeBtnHint}>
            An LLM generates keyword sets from your description. Best for niche or cross-disciplinary topics.
          </span>
        </button>
      </div>

      {/* Preset selection */}
      {mode === "presets" && (
        <div className={styles.presetSection}>
          <label className={styles.label}>Select topics</label>
          <div className={styles.presetGrid}>
            {presets.map((p) => (
              <div
                key={p.name}
                className={styles.presetCard}
                data-selected={selectedPresets.has(p.name)}
                onClick={() => togglePreset(p.name)}
                role="button"
                tabIndex={0}
                onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && togglePreset(p.name)}
              >
                <div className={styles.presetCardHeader}>
                  <span className={styles.presetName}>{p.name}</span>
                  {p.created_by && (
                    <span className={styles.customBadge}>by {p.created_by}</span>
                  )}
                </div>
                <span className={styles.presetDesc}>{p.description}</span>
                <span className={styles.presetKeywords}>
                  {p.include_any.slice(0, 5).join(", ")}
                  {p.include_any.length > 5 && ` +${p.include_any.length - 5} more`}
                </span>
                {p.created_by && p.id && (
                  <button
                    className={styles.presetDeleteBtn}
                    onClick={(e) => handleDeletePreset(e, p.id)}
                    title="Delete preset"
                  >
                    x
                  </button>
                )}
              </div>
            ))}
          </div>

          {showCreator ? (
            <PresetCreator
              onSave={handleCreatePreset}
              onCancel={() => setShowCreator(false)}
            />
          ) : (
            <button
              className={styles.addTopic}
              onClick={() => setShowCreator(true)}
            >
              + Create custom preset
            </button>
          )}

          <div className={styles.stepActions}>
            <button
              className={styles.secondaryBtn}
              onClick={() => setMode(null)}
            >
              Back
            </button>
            <button
              className={styles.primaryBtn}
              onClick={handleUsePresets}
              disabled={selectedPresets.size === 0}
              style={{ marginTop: 0 }}
            >
              Use {selectedPresets.size} selected topic{selectedPresets.size !== 1 ? "s" : ""}
            </button>
          </div>
        </div>
      )}

      {/* Description mode */}
      {mode === "describe" && (
        <>
          <p className={styles.disclaimer}>
            This uses free open-source LLM APIs to generate topics. The models can be busy at times, so generation may fail — just try again if it does.
          </p>
          <div className={styles.fieldGroup}>
            <label className={styles.label}>Describe your research</label>
            <textarea
              className={styles.textarea}
              placeholder="e.g. I work on automated segmentation of myelinated axons in serial block-face electron microscopy (SBEM) volumes. We use deep learning methods like nnU-Net and are interested in connectomics and myelin quantification."
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>

          {!showAbstracts && (
            <button
              className={styles.abstractToggle}
              onClick={() => setShowAbstracts(true)}
            >
              + Add seed paper abstracts (optional)
            </button>
          )}

          {showAbstracts &&
            [0, 1, 2].map((i) => (
              <div key={i} className={styles.abstractSlot}>
                <div className={styles.abstractHeader}>
                  <label className={styles.label}>Abstract {i + 1}</label>
                  {abstracts[i] && (
                    <button
                      className={styles.removeBtn}
                      onClick={() => {
                        const next = [...abstracts];
                        next[i] = "";
                        setAbstracts(next);
                      }}
                    >
                      clear
                    </button>
                  )}
                </div>
                <textarea
                  className={styles.textareaSmall}
                  placeholder="Paste an abstract from a paper you find relevant..."
                  value={abstracts[i] || ""}
                  onChange={(e) => {
                    const next = [...abstracts];
                    next[i] = e.target.value;
                    setAbstracts(next);
                  }}
                />
              </div>
            ))}

          {error && (
            <p className={styles.error}>
              {error} — press the button below to try again.
            </p>
          )}

          <div className={styles.stepActions}>
            <button
              className={styles.secondaryBtn}
              onClick={() => setMode(null)}
            >
              Back
            </button>
            <button
              className={styles.primaryBtn}
              onClick={handleGenerate}
              disabled={loading || !description.trim()}
              style={{ marginTop: 0 }}
            >
              {loading ? "Generating topics..." : error ? "Try again" : "Generate my topics"}
            </button>
          </div>
        </>
      )}
    </>
  );
}

// ── Step 2: Review topics ──

function SourceStatus({ name, status, count }) {
  const icon = status === "done" ? "✓" : status === "failed" ? "✗" : "·";
  const label =
    status === "done"
      ? `${count ?? 0} papers`
      : status === "failed"
        ? "failed"
        : "searching...";

  return (
    <div className={styles.sourceRow} data-status={status}>
      <span className={styles.sourceIcon}>{icon}</span>
      <span className={styles.sourceName}>{name}</span>
      <span className={styles.sourceLabel}>{label}</span>
    </div>
  );
}

function StepReviewTopics({ topics, onChange, onNext, onBack }) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [sourceStatus, setSourceStatus] = useState({});

  function updateTopic(idx, field, value) {
    const updated = [...topics];
    updated[idx] = { ...updated[idx], [field]: value };
    onChange(updated);
  }

  async function handleFindPapers() {
    setLoading(true);
    setError("");
    setSourceStatus({});
    try {
      await onNext((event) => {
        const key = `${event.source} — ${event.topic}`;
        setSourceStatus((prev) => ({
          ...prev,
          [key]: { name: event.source, topic: event.topic, status: event.status, count: event.count, error: event.error },
        }));
      });
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  if (loading) {
    const sources = ["arXiv", "Semantic Scholar", "bioRxiv", "Papers With Code"];
    const allKeys = topics.flatMap((t) =>
      sources.map((s) => ({ key: `${s} — ${t.name}`, source: s, topic: t.name }))
    );

    const doneCount = Object.values(sourceStatus).filter((e) => e.status === "done").length;
    const totalCount = allKeys.length;

    return (
      <div className={styles.loadingState}>
        <h1 className={styles.title}>Searching for papers...</h1>
        <p className={styles.progressSummary}>
          {doneCount} / {totalCount} sources done
        </p>
        <div className={styles.sourceList}>
          {allKeys.map(({ key }) => {
            const entry = sourceStatus[key];
            return (
              <SourceStatus
                key={key}
                name={key}
                status={entry?.status || "pending"}
                count={entry?.count}
              />
            );
          })}
        </div>
        {error && <p className={styles.error}>{error}</p>}
      </div>
    );
  }

  return (
    <>
      <h1 className={styles.title}>Review your topics</h1>
      <p className={styles.subtitle}>
        Edit the generated keywords to fine-tune what papers you'll see.
      </p>

      {topics.map((topic, i) => (
        <div key={i} className={styles.topicCard}>
          <div className={styles.topicHeader}>
            <input
              className={styles.topicNameInput}
              value={topic.name}
              onChange={(e) => updateTopic(i, "name", e.target.value)}
            />
            {topics.length > 1 && (
              <button
                className={styles.removeTopic}
                onClick={() => onChange(topics.filter((_, j) => j !== i))}
              >
                Remove
              </button>
            )}
          </div>

          <div className={styles.tagSection}>
            <div className={styles.tagLabel}>Must contain (all required)</div>
            <TagEditor
              tags={topic.include_all || []}
              onChange={(tags) => updateTopic(i, "include_all", tags)}
              type="required"
            />
          </div>

          <div className={styles.tagSection}>
            <div className={styles.tagLabel}>Related terms (any match)</div>
            <TagEditor
              tags={topic.include_any || []}
              onChange={(tags) => updateTopic(i, "include_any", tags)}
            />
          </div>

          <div className={styles.tagSection}>
            <div className={styles.tagLabel}>Exclude</div>
            <TagEditor
              tags={topic.exclude || []}
              onChange={(tags) => updateTopic(i, "exclude", tags)}
              type="exclude"
            />
          </div>
        </div>
      ))}

      <button
        className={styles.addTopic}
        onClick={() =>
          onChange([
            ...topics,
            { name: "new-topic", include_all: [], include_any: [], exclude: [], boost_authors: [], boost_venues: [] },
          ])
        }
      >
        + Add topic
      </button>

      {error && <p className={styles.error}>{error}</p>}

      <div className={styles.stepActions}>
        <button className={styles.secondaryBtn} onClick={onBack}>
          Back
        </button>
        <button className={styles.primaryBtn} onClick={handleFindPapers} style={{ marginTop: 0 }}>
          Looks good, find papers
        </button>
      </div>
    </>
  );
}

// ── Step 3: Rate papers ──

function StepRatePapers({ papers, feedback, onFeedback, onNext, loading }) {
  const ratedCount = Object.keys(feedback).length;
  const minRatings = Math.min(3, papers.length);

  return (
    <>
      <h1 className={styles.title}>Rate these papers to calibrate your feed</h1>
      <p className={styles.counter}>
        <span className={styles.counterBold}>{ratedCount}</span> rated
        {ratedCount < minRatings && ` — rate at least ${minRatings} to continue`}
      </p>

      <div className={styles.paperList}>
        {papers.map((paper) => (
          <PaperCard
            key={paper.source_id}
            paper={paper}
            showFeedback
            activeSignal={feedback[paper.source_id]}
            onFeedback={(p, signal) => onFeedback(p.source_id, signal)}
          />
        ))}
      </div>

      <button
        className={styles.primaryBtn}
        onClick={onNext}
        disabled={ratedCount < minRatings || loading}
      >
        {loading ? "Saving your preferences..." : "Refine my feed"}
      </button>
    </>
  );
}

// ── Step 4: Saving animation ──

function StepSaving() {
  return (
    <div className={styles.savingState}>
      <div className={styles.savingOrb} />
      <h1 className={styles.savingTitle}>Building your feed</h1>
      <p className={styles.savingSubtitle}>
        Calibrating relevance scores based on your feedback...
      </p>
    </div>
  );
}

// ── Main wizard ──

export default function Onboarding() {
  const navigate = useNavigate();
  const { user } = useUser();
  const [step, setStep] = useState(1);
  const [topics, setTopics] = useState([]);
  const [description, setDescription] = useState("");
  const [seedAbstracts, setSeedAbstracts] = useState([]);
  const [papers, setPapers] = useState([]);
  const [feedback, setFeedback] = useState({});
  const [loading, setLoading] = useState(false);

  const userName = user?.name || "";

  function handleWelcomeNext({ topics: t, description: d, seedAbstracts: sa }) {
    setTopics(t);
    setDescription(d || "");
    setSeedAbstracts(sa || []);
    setStep(2);
  }

  async function handleFindPapers(onProgress) {
    const data = await runFirstPass(topics, userName, onProgress, seedAbstracts, description);
    setPapers(data.papers);
    setStep(3);
  }

  function handleFeedback(sourceId, signal) {
    setFeedback((prev) => {
      if (prev[sourceId] === signal) {
        const next = { ...prev };
        delete next[sourceId];
        return next;
      }
      return { ...prev, [sourceId]: signal };
    });
  }

  async function handleRefine() {
    setStep(4); // show saving animation immediately
    try {
      const fbList = Object.entries(feedback).map(([source_id, signal]) => ({
        source_id,
        signal,
      }));
      const data = await completeOnboarding(userName, topics, fbList);
      const profileId = data.profile_id;
      // Brief pause so the animation is visible
      await new Promise((r) => setTimeout(r, 1500));
      navigate(profileId ? `/digest?profile=${profileId}` : "/digest");
    } catch {
      // If it fails, go back to rating step
      setStep(3);
    }
  }

  return (
    <main className={styles.page}>
      <button className={styles.brand} onClick={() => navigate("/digest")}>ourak<span>.</span></button>
      <StepIndicator step={step} />

      {step === 1 && <StepWelcome onNext={handleWelcomeNext} />}

      {step === 2 && (
        <StepReviewTopics
          topics={topics}
          onChange={setTopics}
          onNext={handleFindPapers}
          onBack={() => setStep(1)}
        />
      )}

      {step === 3 && (
        <StepRatePapers
          papers={papers}
          feedback={feedback}
          onFeedback={handleFeedback}
          onNext={handleRefine}
          loading={loading}
        />
      )}

      {step === 4 && <StepSaving />}
    </main>
  );
}
