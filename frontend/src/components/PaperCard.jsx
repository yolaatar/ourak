import { useState } from "react";
import styles from "./PaperCard.module.css";

function truncateAuthors(authors, max = 3) {
  if (!authors || authors.length === 0) return "Unknown authors";
  const shown = authors.slice(0, max).join(", ");
  return authors.length > max ? `${shown} et al.` : shown;
}

export default function PaperCard({ paper, onFeedback, showFeedback = true, activeSignal }) {
  const [expanded, setExpanded] = useState(false);
  const abstract = paper.abstract || "";
  const snippet = abstract.length > 200 && !expanded
    ? abstract.slice(0, 200) + "..."
    : abstract;

  return (
    <article className={styles.card}>
      <div className={styles.header}>
        <span className={styles.badge} data-source={paper.source}>
          {paper.source}
        </span>
        {paper.published_date && (
          <span className={styles.date}>{paper.published_date}</span>
        )}
      </div>

      <h3 className={styles.title}>
        {paper.url ? (
          <a href={paper.url} target="_blank" rel="noopener noreferrer">
            {paper.title}
          </a>
        ) : (
          paper.title
        )}
      </h3>

      <p className={styles.authors}>{truncateAuthors(paper.authors)}</p>

      {abstract && (
        <div className={styles.abstract}>
          <p>{snippet}</p>
          {abstract.length > 200 && (
            <button
              className={styles.showMore}
              onClick={() => setExpanded(!expanded)}
            >
              {expanded ? "show less" : "show more"}
            </button>
          )}
        </div>
      )}

      <div className={styles.footer}>
        <span className={styles.score}>
          {paper.journal && `${paper.journal} · `}
          score {paper.score?.toFixed(1)}
        </span>

        {showFeedback && onFeedback && (
          <div className={styles.feedbackButtons}>
            <button
              className={styles.feedbackBtn}
              data-signal="upvote"
              data-active={activeSignal === "upvote"}
              onClick={() => onFeedback(paper, "upvote")}
            >
              👍 relevant
            </button>
            <button
              className={styles.feedbackBtn}
              data-signal="flag"
              data-active={activeSignal === "flag"}
              onClick={() => onFeedback(paper, "flag")}
            >
              🚩 off-topic
            </button>
          </div>
        )}
      </div>
    </article>
  );
}
