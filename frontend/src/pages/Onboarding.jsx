import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { generateTopics, runFirstPass, completeOnboarding } from "../api";
import PaperCard from "../components/PaperCard";
import styles from "./Onboarding.module.css";

const TOTAL_STEPS = 4;

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

// ── Step 1: Welcome ──

function StepWelcome({ onNext }) {
  const [description, setDescription] = useState("");
  const [abstracts, setAbstracts] = useState([]);
  const [showAbstracts, setShowAbstracts] = useState(false);
  const [userName, setUserName] = useState("");
  const [userEmail, setUserEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleGenerate() {
    if (!description.trim() || !userName.trim() || !userEmail.trim()) return;
    setLoading(true);
    setError("");
    try {
      const data = await generateTopics(description, abstracts.filter(Boolean));
      onNext({
        topics: data.topics,
        description,
        userName,
        userEmail,
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
        Describe your research and we'll configure a paper feed for you.
      </p>

      <div className={styles.inlineFields}>
        <div>
          <label className={styles.label}>Your name</label>
          <input
            className={styles.input}
            placeholder="Jane Doe"
            value={userName}
            onChange={(e) => setUserName(e.target.value)}
          />
        </div>
        <div>
          <label className={styles.label}>Email</label>
          <input
            className={styles.input}
            type="email"
            placeholder="jane@lab.org"
            value={userEmail}
            onChange={(e) => setUserEmail(e.target.value)}
          />
        </div>
      </div>

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

      <button
        className={styles.primaryBtn}
        onClick={handleGenerate}
        disabled={loading || !description.trim() || !userName.trim() || !userEmail.trim()}
      >
        {loading ? "Generating topics..." : error ? "Try again" : "Generate my topics"}
      </button>
    </>
  );
}

// ── Step 2: Review topics ──

function SourceStatus({ name, status }) {
  const icon = status === "done" ? "+" : status === "failed" ? "x" : " ";
  const label =
    status === "done"
      ? "done"
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

function StepReviewTopics({ topics, onChange, onNext }) {
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
    const sources = ["PubMed", "arXiv", "Semantic Scholar", "bioRxiv", "Papers With Code"];
    const allKeys = topics.flatMap((t) =>
      sources.map((s) => ({ key: `${s} — ${t.name}`, source: s, topic: t.name }))
    );

    return (
      <div className={styles.loadingState}>
        <h1 className={styles.title}>Searching for papers...</h1>
        <div className={styles.sourceList}>
          {allKeys.map(({ key, source }) => {
            const entry = sourceStatus[key];
            return (
              <SourceStatus
                key={key}
                name={key}
                status={entry?.status || "pending"}
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

      <button className={styles.primaryBtn} onClick={handleFindPapers}>
        Looks good, find papers
      </button>
    </>
  );
}

// ── Step 3: Rate papers ──

function StepRatePapers({ papers, feedback, onFeedback, onNext }) {
  const ratedCount = Object.keys(feedback).length;
  const minRatings = Math.min(5, papers.length);

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
        disabled={ratedCount < minRatings}
      >
        Refine my feed
      </button>
    </>
  );
}

// ── Step 4: Refined results ──

function StepRefined({ papers, userName, userEmail, onFinish, loading }) {
  return (
    <>
      <h1 className={styles.title}>Your refined feed</h1>
      <p className={styles.subtitle}>
        Based on your feedback, here are the top papers we think you'll care about.
      </p>

      <div className={styles.userInfo}>
        <span className={styles.userInfoLabel}>Signed up as</span>
        <span className={styles.userInfoValue}>
          {userName} ({userEmail})
        </span>
      </div>

      <div className={styles.paperList}>
        {papers.map((paper) => (
          <PaperCard
            key={paper.source_id}
            paper={paper}
            showFeedback={false}
          />
        ))}
      </div>

      <button className={styles.primaryBtn} onClick={onFinish} disabled={loading}>
        {loading ? "Saving..." : "Start using ourak"}
      </button>
    </>
  );
}

// ── Main wizard ──

export default function Onboarding() {
  const navigate = useNavigate();
  const [step, setStep] = useState(1);
  const [topics, setTopics] = useState([]);
  const [userName, setUserName] = useState("");
  const [userEmail, setUserEmail] = useState("");
  const [seedAbstracts, setSeedAbstracts] = useState([]);
  const [papers, setPapers] = useState([]);
  const [refinedPapers, setRefinedPapers] = useState([]);
  const [feedback, setFeedback] = useState({});
  const [loading, setLoading] = useState(false);

  function handleWelcomeNext({ topics: t, userName: n, userEmail: e, seedAbstracts: sa }) {
    setTopics(t);
    setUserName(n);
    setUserEmail(e);
    setSeedAbstracts(sa || []);
    setStep(2);
  }

  async function handleFindPapers(onProgress) {
    const data = await runFirstPass(topics, userEmail, userName, onProgress, seedAbstracts);
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
    setLoading(true);
    try {
      const fbList = Object.entries(feedback).map(([source_id, signal]) => ({
        source_id,
        signal,
      }));
      const data = await completeOnboarding(userName, userEmail, topics, fbList);
      localStorage.setItem("userId", data.user_id);
      localStorage.setItem("userName", userName);
      // For step 4, show the papers re-sorted by feedback
      const upvoted = new Set(
        fbList.filter((f) => f.signal === "upvote").map((f) => f.source_id)
      );
      const flagged = new Set(
        fbList.filter((f) => f.signal === "flag").map((f) => f.source_id)
      );
      const sorted = [...papers]
        .map((p) => ({
          ...p,
          score: p.score + (upvoted.has(p.source_id) ? 5 : 0) + (flagged.has(p.source_id) ? -10 : 0),
        }))
        .sort((a, b) => b.score - a.score)
        .slice(0, 10);
      setRefinedPapers(sorted);
      setStep(4);
    } finally {
      setLoading(false);
    }
  }

  async function handleFinish() {
    navigate("/digest");
  }

  return (
    <main className={styles.page}>
      <StepIndicator step={step} />

      {step === 1 && <StepWelcome onNext={handleWelcomeNext} />}

      {step === 2 && (
        <StepReviewTopics
          topics={topics}
          onChange={setTopics}
          onNext={handleFindPapers}
        />
      )}

      {step === 3 && (
        <StepRatePapers
          papers={papers}
          feedback={feedback}
          onFeedback={handleFeedback}
          onNext={handleRefine}
        />
      )}

      {step === 4 && (
        <StepRefined
          papers={refinedPapers}
          userName={userName}
          userEmail={userEmail}
          onFinish={handleFinish}
          loading={loading}
        />
      )}
    </main>
  );
}
