document.addEventListener("DOMContentLoaded", () => {
  document.documentElement.classList.add("js-reveal");

  // Normalize any stale same-site .md links to pretty URL routes.
  document.querySelectorAll("a[href]").forEach((a) => {
    const raw = (a.getAttribute("href") || "").trim();
    if (!raw || raw.startsWith("http://") || raw.startsWith("https://") || raw.startsWith("mailto:") || raw.startsWith("tel:") || raw.startsWith("#")) return;
    const hashIdx = raw.indexOf("#");
    const qIdx = raw.indexOf("?");
    let endIdx = raw.length;
    if (hashIdx >= 0) endIdx = Math.min(endIdx, hashIdx);
    if (qIdx >= 0) endIdx = Math.min(endIdx, qIdx);
    const path = raw.slice(0, endIdx);
    if (!path.toLowerCase().endsWith(".md")) return;
    const suffix = raw.slice(endIdx);
    a.setAttribute("href", `${path.slice(0, -3)}/${suffix}`);
  });

  const targets = document.querySelectorAll(
    [
      ".landing-hero",
      ".landing-card",
      ".info-panel",
      ".route-card",
      ".topic-card",
      ".topic-hero",
      ".paper-card",
      ".top-idea",
      "#paper-graph",
      ".paper-panel",
      ".tools-panel",
      ".panel",
      ".md-typeset h2",
      ".md-typeset h3",
    ].join(", ")
  );
  // Also pick up any elements that statically declare `.reveal` in markup
  // (e.g. inside explorer.md), so the IntersectionObserver actually unhides them.
  const staticReveal = document.querySelectorAll(".reveal");
  const allTargets = new Set([...targets, ...staticReveal]);
  if (!allTargets.size) return;

  allTargets.forEach((el) => el.classList.add("reveal"));

  if (!("IntersectionObserver" in window)) {
    allTargets.forEach((el) => el.classList.add("in-view"));
    return;
  }

  const observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (entry.isIntersecting) {
          entry.target.classList.add("in-view");
          observer.unobserve(entry.target);
        }
      }
    },
    { rootMargin: "0px 0px -6% 0px", threshold: 0.12 }
  );

  allTargets.forEach((el) => observer.observe(el));
});
