import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getPapers, getTopics } from "../api";
import Header from "../components/Header";
import PaperCard from "../components/PaperCard";
import styles from "./Digest.module.css";

const PAGE_SIZE = 20;
const SOURCES = ["arxiv", "semantic_scholar", "biorxiv", "paperswithcode"];

export default function Digest() {
  const navigate = useNavigate();
  const [papers, setPapers] = useState([]);
  const [topics, setTopics] = useState([]);
  const [activeTopic, setActiveTopic] = useState(null);
  const [sortBy, setSortBy] = useState("score");
  const [activeSource, setActiveSource] = useState(null);
  const [loading, setLoading] = useState(true);
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(true);

  const userId = localStorage.getItem("userId");
  const userName = localStorage.getItem("userName");

  useEffect(() => {
    if (!userId) {
      navigate("/onboarding");
      return;
    }
    loadTopics();
    loadPapers(0);
  }, []);

  async function loadTopics() {
    try {
      const data = await getTopics();
      setTopics(data);
    } catch {
      // ignore — topics are optional decoration
    }
  }

  async function loadPapers(newOffset, topicId = activeTopic, sort = sortBy, source = activeSource) {
    setLoading(true);
    try {
      const data = await getPapers({
        userId,
        topicId,
        sortBy: sort,
        source,
        limit: PAGE_SIZE,
        offset: newOffset,
      });
      if (newOffset === 0) {
        setPapers(data);
      } else {
        setPapers((prev) => [...prev, ...data]);
      }
      setHasMore(data.length === PAGE_SIZE);
      setOffset(newOffset + data.length);
    } catch (err) {
      console.error("Failed to load papers:", err);
    } finally {
      setLoading(false);
    }
  }

  function handleTopicFilter(topicId) {
    const next = topicId === activeTopic ? null : topicId;
    setActiveTopic(next);
    setOffset(0);
    loadPapers(0, next, sortBy, activeSource);
  }

  function handleSortChange(newSort) {
    setSortBy(newSort);
    setOffset(0);
    loadPapers(0, activeTopic, newSort, activeSource);
  }

  function handleSourceFilter(source) {
    const next = source === activeSource ? null : source;
    setActiveSource(next);
    setOffset(0);
    loadPapers(0, activeTopic, sortBy, next);
  }

  return (
    <div className={styles.page}>
      <Header userName={userName} />
      <main className={styles.content}>
        {/* Topic filter pills */}
        {topics.length > 0 && (
          <div className={styles.filters}>
            <button
              className={styles.filterPill}
              data-active={activeTopic === null}
              onClick={() => handleTopicFilter(null)}
            >
              All
            </button>
            {topics.map((t) => (
              <button
                key={t.id}
                className={styles.filterPill}
                data-active={activeTopic === t.id}
                onClick={() => handleTopicFilter(t.id)}
              >
                {t.name}
              </button>
            ))}
          </div>
        )}

        {/* Sort + source filter bar */}
        <div className={styles.controlBar}>
          <div className={styles.controlGroup}>
            <span className={styles.controlLabel}>Sort by</span>
            <button
              className={styles.controlBtn}
              data-active={sortBy === "score"}
              onClick={() => handleSortChange("score")}
            >
              Relevance
            </button>
            <button
              className={styles.controlBtn}
              data-active={sortBy === "date"}
              onClick={() => handleSortChange("date")}
            >
              Date
            </button>
          </div>
          <div className={styles.controlGroup}>
            <span className={styles.controlLabel}>Source</span>
            <button
              className={styles.controlBtn}
              data-active={activeSource === null}
              onClick={() => handleSourceFilter(null)}
            >
              All
            </button>
            {SOURCES.map((s) => (
              <button
                key={s}
                className={styles.controlBtn}
                data-active={activeSource === s}
                onClick={() => handleSourceFilter(s)}
              >
                {s === "semantic_scholar" ? "S2" : s === "paperswithcode" ? "PWC" : s}
              </button>
            ))}
          </div>
        </div>

        {loading && papers.length === 0 ? (
          <div className={styles.paperList}>
            {[1, 2, 3].map((i) => (
              <div key={i} className={styles.skeleton} />
            ))}
          </div>
        ) : papers.length === 0 ? (
          <p className={styles.empty}>
            No papers yet. Your feed will populate on the next run.
          </p>
        ) : (
          <>
            <div className={styles.paperList}>
              {papers.map((paper) => (
                <PaperCard
                  key={paper.source_id}
                  paper={paper}
                  showFeedback={false}
                />
              ))}
            </div>
            {hasMore && (
              <button
                className={styles.loadMore}
                onClick={() => loadPapers(offset)}
                disabled={loading}
              >
                {loading ? "Loading..." : "Load more"}
              </button>
            )}
          </>
        )}
      </main>
    </div>
  );
}
