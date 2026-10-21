/* DataSemver site. The little script the page has: the copy buttons, and the motion.

   Every part of the motion is an addition. The page is complete without any of it, and each
   feature is wrapped so that one failing does not take the others with it. A reader who asks
   their system for less motion gets none of it: nothing here starts, and nothing is left hidden
   waiting to be revealed. */
(() => {
  const root = document.documentElement;
  const calm = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  const attempt = (feature) => {
    try {
      feature();
    } catch (error) {
      console.warn("site.js:", error);
    }
  };

  // ---------- copy buttons ----------
  attempt(() => {
    for (const button of document.querySelectorAll("[data-copy]")) {
      button.addEventListener("click", async () => {
        const label = button.textContent;
        try {
          await navigator.clipboard.writeText(button.dataset.copy);
          button.textContent = button.dataset.done || "Copied";
        } catch {
          button.textContent = button.dataset.fail || "Press Ctrl+C";
        }
        setTimeout(() => {
          button.textContent = label;
        }, 1600);
      });
    }
  });

  // ---------- reveal on scroll ----------
  // What is already on screen is left alone: the hero has its own entrance, and an element that
  // were hidden for one frame only to appear again would flicker rather than arrive. The rest
  // waits, invisible, until it is a little way into the window, then settles into place with a
  // delay that grows along its row so a group arrives as a group.
  attempt(() => {
    if (calm || !("IntersectionObserver" in window)) {
      return;
    }
    const groups = [
      [".reason > *", 1],
      ["section > h2, section > .say, section > .after-ladder", 1],
      [".ladder > .rung", 1],
      [".surfaces > div", 2],
      [".pair > *", 1],
      [".full", 1],
      ["section .facts", 1],
      [".scroll-x", 1],
      ["section > pre", 1],
      [".cta > *", 1],
    ];

    const seen = new Set();
    const waiting = [];
    for (const [selector, columns] of groups) {
      const perParent = new Map();
      for (const element of document.querySelectorAll(selector)) {
        if (seen.has(element)) {
          continue;
        }
        seen.add(element);
        const index = perParent.get(element.parentElement) ?? 0;
        perParent.set(element.parentElement, index + 1);
        if (element.getBoundingClientRect().top < window.innerHeight) {
          continue;
        }
        // Down a column the delay grows with the position; across a grid it follows the column,
        // so two cells side by side arrive one after the other and the next row starts over.
        element.style.setProperty("--i", String(columns > 1 ? index % columns : Math.min(index, 4)));
        element.classList.add("reveal");
        waiting.push(element);
      }
    }

    const watcher = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            entry.target.classList.add("in");
            watcher.unobserve(entry.target);
          }
        }
      },
      { rootMargin: "0px 0px -9% 0px", threshold: 0.06 },
    );
    waiting.forEach((element) => watcher.observe(element));
  });

  // ---------- motes: data cells drifting up through the light behind the hero ----------
  // Placed from a fixed seed, so the page is the same on every visit and a screenshot of it is
  // repeatable.
  attempt(() => {
    const wrap = document.querySelector(".hero-wrap");
    if (calm || !wrap) {
      return;
    }
    let seed = 7;
    const random = () => {
      seed = (seed * 16807) % 2147483647;
      return (seed - 1) / 2147483646;
    };
    const layer = document.createElement("div");
    layer.className = "motes";
    layer.setAttribute("aria-hidden", "true");
    for (let n = 0; n < 26; n += 1) {
      const mote = document.createElement("i");
      const onTheShot = random() < 0.72;
      mote.style.cssText = [
        `--x:${(onTheShot ? 46 + random() * 52 : 2 + random() * 40).toFixed(1)}%`,
        `--y:${(14 + random() * 78).toFixed(1)}%`,
        `--s:${(3 + random() * 4).toFixed(1)}px`,
        `--t:${(7 + random() * 7).toFixed(1)}s`,
        `--d:${(-random() * 12).toFixed(1)}s`,
        `--a:${(0.3 + random() * 0.45).toFixed(2)}`,
      ].join(";");
      layer.append(mote);
    }
    wrap.prepend(layer);
  });

  // ---------- the rules, passing by ----------
  // The track holds each rule once in the markup. It is doubled here so that sliding it by half
  // its width lands where it began, and the copy is hidden from anything that reads the page.
  attempt(() => {
    const track = document.querySelector(".ticker-track");
    if (!track || calm) {
      return;
    }
    for (const item of [...track.children]) {
      const copy = item.cloneNode(true);
      copy.dataset.clone = "";
      track.append(copy);
    }
    track.classList.add("is-moving");
  });

  // ---------- counting up ----------
  attempt(() => {
    const figures = document.querySelectorAll("[data-count]");
    if (calm || !figures.length || !("IntersectionObserver" in window)) {
      return;
    }
    const run = (figure) => {
      const target = Number(figure.dataset.count);
      const started = performance.now();
      const length = 1100;
      const step = (now) => {
        const progress = Math.min(1, (now - started) / length);
        const eased = 1 - (1 - progress) ** 3;
        figure.textContent = String(Math.round(target * eased));
        if (progress < 1) {
          requestAnimationFrame(step);
        }
      };
      figure.textContent = "0";
      requestAnimationFrame(step);
    };
    const watcher = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            run(entry.target);
            watcher.unobserve(entry.target);
          }
        }
      },
      { threshold: 0.6 },
    );
    figures.forEach((figure) => watcher.observe(figure));
  });

  root.classList.add("ready");
})();
