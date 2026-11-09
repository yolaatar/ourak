import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { getPapers, getTopics, getProfiles, deleteProfile, refreshProfile } from "../api";
import { useUser } from "../UserContext";
import Header from "../components/Header";
import PaperCard from "../components/PaperCard";
import styles from "./Digest.module.css";

const PAGE_SIZE = 20;
const SOURCES = ["arxiv", "semantic_scholar", "biorxiv", "paperswithcode"];

export default function Digest() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const { user, loading: userLoading } = useUser();

  const [papers, setPapers] = useState([]);
  const [topics, setTopics] = useState([]);
  const [profiles, setProfiles] = useState([]);
  const [activeProfileId, setActiveProfileId] = useState(
    Number(searchParams.get("profile")) || null
  );
  const [activeTopic, setActiveTopic] = useState(null);
  const [sortBy, setSortBy] = useState("score");
  const [activeSource, setActiveSource] = useState(null);
  const [loading, setLoading] = useState(true);
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshLogs, setRefreshLogs] = useState([]);

  useEffect(() => {
    if (userLoading) return;
    if (!user) {
      navigate("/login");
      return;
    }
    loadProfiles();
  }, [userLoading, user]);

  useEffect(() => {
    if (!activeProfileId) return;
    loadTopics(activeProfileId);
    loadPapers(0, null, sortBy, activeSource, activeProfileId);
  }, [activeProfileId]);

  async function loadProfiles() {
    try {
      const data = await getProfiles();
      setProfiles(data);
      // If no profile selected, use the first one
      if (!activeProfileId && data.length > 0) {
        setActiveProfileId(data[0].id);
        setSearchParams({ profile: data[0].id });
      } else if (data.length === 0) {
        navigate("/onboarding");
      }
    } catch {
      // ignore
    }
  }

  async function loadTopics(profileId) {
    try {
      const data = await getTopics(profileId);
      setTopics(data);
    } catch {
      // ignore
    }
  }

  async function loadPapers(newOffset, topicId = activeTopic, sort = sortBy, source = activeSource, profileId = activeProfileId) {
    setLoading(true);
    try {
      const data = await getPapers({
        userId: user?.id,
        topicId,
        profileId,
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

  function handleProfileChange(profileId) {
    setActiveProfileId(profileId);
    setActiveTopic(null);
    setOffset(0);
    setSearchParams({ profile: profileId });
  }

  function handleTopicFilter(topicId) {
    const next = topicId === activeTopic ? null : topicId;
    setActiveTopic(next);
    setOffset(0);
    loadPapers(0, next, sortBy, activeSource, activeProfileId);
  }

  function handleSortChange(newSort) {
    setSortBy(newSort);
    setOffset(0);
    loadPapers(0, activeTopic, newSort, activeSource, activeProfileId);
  }

  function handleSourceFilter(source) {
    const next = source === activeSource ? null : source;
    setActiveSource(next);
    setOffset(0);
    loadPapers(0, activeTopic, sortBy, next, activeProfileId);
  }

  async function handleRefresh() {
    if (!activeProfileId || refreshing) return;
    setRefreshing(true);
    setRefreshLogs([]);
    try {
      await refreshProfile(activeProfileId, (event) => {
        setRefreshLogs((prev) => {
          const key = `${event.source}|${event.topic}`;
          const existing = prev.findIndex((l) => l.key === key);
          const entry = {
            key,
            source: event.source,
            topic: event.topic,
            status: event.status,
            count: event.count ?? 0,
            finished: event.finished,
            total: event.total,
          };
          if (existing >= 0) {
            const next = [...prev];
            next[existing] = entry;
            return next;
          }
          return [...prev, entry];
        });
      });
      await loadProfiles();
      loadPapers(0, activeTopic, sortBy, activeSource, activeProfileId);
    } catch (err) {
      console.error("Refresh failed:", err);
    } finally {
      setRefreshing(false);
    }
  }

  function getStaleDays() {
    const profile = profiles.find((p) => p.id === activeProfileId);
    if (!profile?.last_fetched_at) return null;
    const diff = Date.now() - new Date(profile.last_fetched_at).getTime();
    return Math.floor(diff / (1000 * 60 * 60 * 24));
  }

  async function handleDeleteProfile(e, profileId) {
    e.stopPropagation();
    if (!confirm("Delete this search and its papers?")) return;
    await deleteProfile(profileId);
    const remaining = profiles.filter((p) => p.id !== profileId);
    setProfiles(remaining);
    if (activeProfileId === profileId) {
      if (remaining.length > 0) {
        handleProfileChange(remaining[0].id);
      } else {
        navigate("/onboarding");
      }
    }
  }

  return (
    <div className={styles.page}>
      <Header />
      <main className={styles.content}>
        {/* Profile switcher */}
        {profiles.length > 0 && (
          <div className={styles.profileBar}>
            <div className={styles.profileList}>
              {profiles.map((p) => (
                <div key={p.id} className={styles.profilePillWrap}>
                  <button
                    className={styles.profilePill}
                    data-active={p.id === activeProfileId}
                    onClick={() => handleProfileChange(p.id)}
                  >
                    {p.name}
                  </button>
                  <button
                    className={styles.profileDeleteBtn}
                    onClick={(e) => handleDeleteProfile(e, p.id)}
                    title="Delete search"
                  >
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <line x1="18" y1="6" x2="6" y2="18" />
                      <line x1="6" y1="6" x2="18" y2="18" />
                    </svg>
                  </button>
                </div>
              ))}
            </div>
            <button
              className={styles.newSearchBtn}
              onClick={() => navigate("/onboarding")}
            >
              + New search
            </button>
          </div>
        )}

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

        {/* Stale feed banner */}
        {(() => {
          const days = getStaleDays();
          return days !== null && days >= 7 ? (
            <div className={styles.staleBanner}>
              <span>Feed last updated {days} day{days !== 1 ? "s" : ""} ago</span>
              <button
                className={styles.refreshBtn}
                onClick={handleRefresh}
                disabled={refreshing}
              >
                {refreshing ? "Refreshing..." : "Refresh now"}
              </button>
            </div>
          ) : (
            <div className={styles.refreshRow}>
              <button
                className={styles.refreshBtnQuiet}
                onClick={handleRefresh}
                disabled={refreshing}
              >
                {refreshing ? "Refreshing..." : "↻ Refresh"}
              </button>
            </div>
          );
        })()}

        {/* Refresh progress log */}
        {refreshing && refreshLogs.length > 0 && (
          <div className={styles.refreshLog}>
            <div className={styles.refreshLogHeader}>
              <span>{refreshLogs.filter((l) => l.status === "done").length} / {refreshLogs[refreshLogs.length - 1]?.total ?? "?"} sources done</span>
            </div>
            <div className={styles.refreshLogRows}>
              {refreshLogs.map((l) => (
                <div key={l.key} className={styles.refreshLogRow} data-status={l.status}>
                  <span className={styles.refreshLogSource}>{l.source}</span>
                  <span className={styles.refreshLogTopic}>{l.topic}</span>
                  <span className={styles.refreshLogCount}>
                    {l.status === "done" ? `${l.count} papers` : "failed"}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

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
