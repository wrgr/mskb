document.addEventListener("DOMContentLoaded", () => {
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
      ".panel",
      ".md-typeset h2",
      ".md-typeset h3",
    ].join(", ")
  );
  if (!targets.length) return;

  targets.forEach((el) => el.classList.add("reveal"));

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

  targets.forEach((el) => observer.observe(el));
});
