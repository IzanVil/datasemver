/* DataSemver site: the menus, the copy buttons, the tabs, the chart, and the motion.
   The page is whole without any of it. Each part runs on its own, so one failing leaves the
   others alone, and a reader who asks for less motion gets the still version of every part. */

(() => {
  const root = document.documentElement;
  const calm = matchMedia("(prefers-reduced-motion: reduce)");
  const phone = matchMedia("(max-width: 640px)");
  const fine = matchMedia("(hover: hover) and (pointer: fine)");
  const lang = root.lang === "es" ? "es" : "en";
  const T = {
    en: { copied: "Copied to the clipboard", pause: "Pause the animation", play: "Play the animation", menu: "Open the menu", close: "Close the menu" },
    es: { copied: "Copiado al portapapeles", pause: "Pausar la animación", play: "Reanudar la animación", menu: "Abrir el menú", close: "Cerrar el menú" },
  }[lang];

  const part = (name, fn) => {
    try {
      fn();
    } catch (error) {
      console.error(`site.js: ${name}`, error);
    }
  };

  /* The hero arrives once: the h1 line by line, then what follows it, the picture settling. */
  part("entrance", () => {
    if (!root.classList.contains("m-enter")) return;
    const go = () =>
      requestAnimationFrame(() => {
        root.classList.add("m-go");
        setTimeout(() => root.classList.remove("m-enter", "m-go"), 1700);
      });
    const fonts = document.fonts ? document.fonts.ready : Promise.resolve();
    Promise.race([fonts, new Promise((resolve) => setTimeout(resolve, 500))]).then(go);
  });

  /* The bar gains its rule once the page has moved under it. */
  part("nav", () => {
    const nav = document.getElementById("nav");
    const onScroll = () => nav.classList.toggle("is-scrolled", scrollY > 8);
    addEventListener("scroll", onScroll, { passive: true });
    onScroll();

    const button = nav.querySelector("[data-mega]");
    const mega = document.getElementById("mega");
    if (!button || !mega) return;
    let timer;
    const set = (open) => {
      clearTimeout(timer);
      button.setAttribute("aria-expanded", String(open));
      mega.classList.toggle("is-open", open);
      nav.classList.toggle("is-open", open);
    };
    button.addEventListener("click", () => set(button.getAttribute("aria-expanded") !== "true"));
    button.addEventListener("pointerenter", () => {
      if (!fine.matches) return;
      clearTimeout(timer);
      timer = setTimeout(() => set(true), 150);
    });
    button.addEventListener("pointerleave", () => clearTimeout(timer));
    nav.addEventListener("pointerleave", () => {
      if (!fine.matches || button.getAttribute("aria-expanded") !== "true") return;
      timer = setTimeout(() => set(false), 200);
    });
    mega.addEventListener("pointerenter", () => clearTimeout(timer));
    mega.addEventListener("click", (event) => {
      if (event.target.closest("a")) set(false);
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && button.getAttribute("aria-expanded") === "true") {
        set(false);
        button.focus();
      }
    });
    document.addEventListener("click", (event) => {
      if (!nav.contains(event.target)) set(false);
    });
  });

  /* The narrow-screen menu: one sheet under the bar. */
  part("menu", () => {
    const button = document.querySelector("[data-menu]");
    const sheet = document.getElementById("sheet");
    if (!button || !sheet) return;
    const icon = button.querySelector("use");
    const set = (open) => {
      button.setAttribute("aria-expanded", String(open));
      button.setAttribute("aria-label", open ? T.close : T.menu);
      icon.setAttribute("href", open ? "#i-close" : "#i-menu");
      sheet.classList.toggle("is-open", open);
      document.getElementById("nav").classList.toggle("is-open", open);
    };
    button.addEventListener("click", () => set(button.getAttribute("aria-expanded") !== "true"));
    sheet.addEventListener("click", (event) => {
      if (event.target.closest("a")) set(false);
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && button.getAttribute("aria-expanded") === "true") {
        set(false);
        button.focus();
      }
    });
    matchMedia("(min-width: 961px)").addEventListener("change", (event) => {
      if (event.matches) set(false);
    });
  });

  /* Copy buttons: the glyph turns to a check for a moment, and a screen reader hears it. */
  part("copy", () => {
    const live = document.createElement("p");
    live.className = "sr";
    live.setAttribute("aria-live", "polite");
    document.body.append(live);
    const write = async (text) => {
      try {
        await navigator.clipboard.writeText(text);
        return true;
      } catch {
        const area = document.createElement("textarea");
        area.value = text;
        area.setAttribute("readonly", "");
        area.style.cssText = "position:fixed;opacity:0";
        document.body.append(area);
        area.select();
        const done = document.execCommand("copy");
        area.remove();
        return done;
      }
    };
    document.querySelectorAll("[data-copy], [data-copy-from]").forEach((button) => {
      let timer;
      button.addEventListener("click", async () => {
        const source = button.dataset.copyFrom && document.getElementById(button.dataset.copyFrom);
        const text = source ? source.textContent.trim() : button.dataset.copy;
        if (!(await write(text))) return;
        button.classList.add("is-done");
        live.textContent = "";
        requestAnimationFrame(() => (live.textContent = T.copied));
        clearTimeout(timer);
        timer = setTimeout(() => button.classList.remove("is-done"), 1800);
      });
    });
  });

  /* Tabs: click or arrow keys; one ink pill travels to the chosen tab by transform alone. */
  part("tabs", () => {
    document.querySelectorAll('[role="tablist"]').forEach((list) => {
      const tabs = [...list.querySelectorAll('[role="tab"]')];
      const ink = list.querySelector(".tabs__ink");
      let current = tabs.find((tab) => tab.getAttribute("aria-selected") === "true") || tabs[0];
      const place = (tab, from) => {
        if (!ink) return;
        ink.classList.remove("is-moving");
        ink.style.width = `${tab.offsetWidth}px`;
        if (from && from !== tab) {
          ink.style.transform = `translateX(${from.offsetLeft}px) scaleX(${from.offsetWidth / tab.offsetWidth})`;
          void ink.offsetWidth;
          ink.classList.add("is-moving");
        }
        ink.style.transform = `translateX(${tab.offsetLeft}px)`;
      };
      const select = (tab, focus) => {
        if (tab === current) return;
        const previous = current;
        current = tab;
        tabs.forEach((other) => {
          const on = other === tab;
          other.setAttribute("aria-selected", String(on));
          other.tabIndex = on ? 0 : -1;
          const panel = document.getElementById(other.getAttribute("aria-controls"));
          panel.hidden = !on;
          panel.classList.toggle("is-in", on);
        });
        place(tab, previous);
        if (focus) tab.focus();
        tab.scrollIntoView({ block: "nearest", inline: "nearest" });
      };
      tabs.forEach((tab, index) => {
        tab.addEventListener("click", () => select(tab, false));
        tab.addEventListener("keydown", (event) => {
          const step = { ArrowRight: 1, ArrowLeft: -1 }[event.key];
          if (step) {
            event.preventDefault();
            select(tabs[(index + step + tabs.length) % tabs.length], true);
          } else if (event.key === "Home" || event.key === "End") {
            event.preventDefault();
            select(tabs[event.key === "Home" ? 0 : tabs.length - 1], true);
          }
        });
      });
      place(current);
      new ResizeObserver(() => place(current)).observe(list);
      if (document.fonts) document.fonts.ready.then(() => place(current));
    });
  });

  /* The engine chart: one measure at a time, every bar against the slowest of that measure. */
  part("chart", () => {
    document.querySelectorAll("[data-chart]").forEach((card) => {
      const fills = [...card.querySelectorAll(".bar__fill")];
      const buttons = [...card.querySelectorAll("[data-metric]")];
      const locale = lang === "es" ? "es-ES" : "en-GB";
      const unit = {
        time: (v) => `${Number(v).toLocaleString(locale, { minimumFractionDigits: 1 })} s`,
        memory: (v) => `${Number(v).toLocaleString(locale, { useGrouping: true })} MB`,
      };
      const show = (metric) => {
        const max = Math.max(...fills.map((fill) => Number(fill.dataset[metric])));
        fills.forEach((fill) => {
          const value = fill.dataset[metric];
          // The longest bar stops short of the edge, so every value sits after its bar.
          const share = (Number(value) / max) * 0.8;
          const track = fill.parentElement;
          const label = track.querySelector(".bar__value");
          track.style.setProperty("--v", share.toFixed(4));
          label.textContent = unit[metric](value);
        });
        buttons.forEach((button) => button.setAttribute("aria-pressed", String(button.dataset.metric === metric)));
      };
      buttons.forEach((button) => button.addEventListener("click", () => show(button.dataset.metric)));
      show("time");
    });
  });

  /* Diagram loops: they run only on screen, restart under the pointer, and carry a pause disc. */
  part("loops", () => {
    const loops = [...document.querySelectorAll("[data-loop]")];
    if (!loops.length) return;
    const runs = new Map();
    const update = (el) => {
      const state = runs.get(el);
      el.classList.toggle("is-running", state.visible && !state.paused && !calm.matches && !phone.matches);
    };
    const restart = (el) => {
      if (!el.classList.contains("is-running")) return;
      el.classList.remove("is-running");
      void el.offsetWidth;
      el.classList.add("is-running");
    };
    loops.forEach((el) => {
      runs.set(el, { visible: false, paused: false });
      const button = document.createElement("button");
      button.type = "button";
      button.className = "pause loop-pause";
      button.setAttribute("aria-pressed", "false");
      button.setAttribute("aria-label", T.pause);
      button.innerHTML = '<svg class="bars-icon" aria-hidden="true"><use href="#i-pause"/></svg><svg class="play" aria-hidden="true"><use href="#i-play"/></svg>';
      button.addEventListener("click", () => {
        const state = runs.get(el);
        state.paused = !state.paused;
        button.setAttribute("aria-pressed", String(state.paused));
        button.setAttribute("aria-label", state.paused ? T.play : T.pause);
        update(el);
      });
      const verdict = el.querySelector(".lanes__verdict");
      (verdict || el).append(button);
      if (!verdict) button.classList.add("loop-pause--float");
      el.addEventListener("pointerenter", () => restart(el));
      el.addEventListener("focusin", () => restart(el));
    });
    const io = new IntersectionObserver(
      (entries) =>
        entries.forEach((entry) => {
          runs.get(entry.target).visible = entry.isIntersecting;
          update(entry.target);
        }),
      { threshold: 0.3 }
    );
    loops.forEach((el) => io.observe(el));
    const all = () => loops.forEach(update);
    calm.addEventListener("change", all);
    phone.addEventListener("change", all);
  });

  /* The hub answers the list: the row under the pointer lights its spoke. */
  part("hub", () => {
    const hub = document.querySelector(".hub");
    if (!hub) return;
    document.querySelectorAll(".way[data-way]").forEach((row) => {
      const spoke = hub.querySelector(`g[data-way="${row.dataset.way}"]`);
      const on = (lit) => {
        row.classList.toggle("is-lit", lit);
        if (spoke) spoke.classList.toggle("is-lit", lit);
      };
      row.addEventListener("pointerenter", () => on(true));
      row.addEventListener("pointerleave", () => on(false));
    });
  });

  /* The formats marquee: a pause button, and the pointer holds it too (CSS). */
  part("marquee", () => {
    document.querySelectorAll("[data-marquee]").forEach((wrap) => {
      const button = wrap.querySelector("[data-pause]");
      if (!button) return;
      const labels = lang === "es"
        ? ["Pausar la lista de formatos en movimiento", "Reanudar la lista de formatos"]
        : ["Pause the moving list of formats", "Play the moving list of formats"];
      button.addEventListener("click", () => {
        const paused = !wrap.classList.contains("is-paused");
        wrap.classList.toggle("is-paused", paused);
        button.setAttribute("aria-pressed", String(paused));
        button.setAttribute("aria-label", labels[paused ? 1 : 0]);
      });
    });
  });

  /* Counter rolls: the figures roll once like an odometer, the right-most digit turning most.
     They rest on the real figures before and after; on a phone and under reduced motion they
     simply stand. */
  part("counters", () => {
    const rows = document.querySelectorAll("[data-counters]");
    rows.forEach((row) => {
      const nums = [...row.querySelectorAll("[data-roll]")];
      nums.forEach((num) => {
        const text = num.firstChild;
        if (!text || text.nodeType !== Node.TEXT_NODE) return;
        const value = text.textContent;
        const reader = document.createElement("span");
        reader.className = "sr";
        reader.textContent = value;
        const shown = document.createElement("span");
        shown.setAttribute("aria-hidden", "true");
        shown.style.display = "inline-flex";
        const digits = [...value].filter((c) => /\d/.test(c)).length;
        let seen = 0;
        [...value].forEach((c) => {
          if (!/\d/.test(c)) {
            const plain = document.createElement("span");
            plain.textContent = c;
            shown.append(plain);
            return;
          }
          seen += 1;
          const fromRight = digits - seen;
          const turns = Math.max(1, 3 - fromRight);
          const d = Number(c);
          const roll = document.createElement("span");
          roll.className = "roll";
          const strip = document.createElement("span");
          strip.style.setProperty("--from", d);
          strip.style.setProperty("--to", d + 10 * turns);
          strip.style.setProperty("--dur", `${900 + 260 * (turns - 1)}ms`);
          for (let i = 0; i < 10 * (turns + 1); i += 1) {
            const cell = document.createElement("span");
            cell.textContent = String(i % 10);
            strip.append(cell);
          }
          roll.append(strip);
          shown.append(roll);
        });
        text.replaceWith(reader, shown);
      });
      if (calm.matches || phone.matches) return;
      const io = new IntersectionObserver(
        (entries) => {
          if (!entries.some((entry) => entry.isIntersecting)) return;
          io.disconnect();
          setTimeout(() => nums.forEach((num) => num.classList.add("is-rolling")), 120);
        },
        { threshold: 0.6 }
      );
      io.observe(row);
    });
  });

  /* The hero ground: soft shapes in the page colours under fine grain. It holds still behind
     the screenshot: drawn once, and again only when the panel changes size. Without WebGL the
     panel's own gradient stays. */
  part("grain", () => {
    const canvas = document.querySelector("canvas[data-grain]");
    if (!canvas) return;
    const gl = canvas.getContext("webgl", { antialias: false, alpha: false, powerPreference: "low-power" });
    if (!gl) return;
    const vs = "attribute vec2 p;void main(){gl_Position=vec4(p,0.,1.);}";
    const fs = `precision mediump float;
uniform vec2 r;uniform float t;uniform float g;uniform vec3 k;
float h(vec2 p){p=fract(p*vec2(123.34,456.21));p+=dot(p,p+45.32);return fract(p.x*p.y);}
float n(vec2 p){vec2 i=floor(p),f=fract(p);f=f*f*(3.-2.*f);
return mix(mix(h(i),h(i+vec2(1,0)),f.x),mix(h(i+vec2(0,1)),h(i+vec2(1,1)),f.x),f.y);}
float fbm(vec2 p){float v=0.,a=.5;for(int i=0;i<5;i++){v+=a*n(p);p=p*2.03+vec2(1.7,9.2);a*=.5;}return v;}
void main(){
vec2 uv=gl_FragCoord.xy/r;vec2 p=uv*vec2(r.x/r.y,1.)*1.6;
float s=t*.035;
vec2 q=vec2(fbm(p+vec2(0.,s)),fbm(p+vec2(5.2,1.3)-s));
vec2 w=vec2(fbm(p+1.6*q+vec2(1.7,9.2)+s*.6),fbm(p+1.6*q+vec2(8.3,2.8)-s*.4));
float f=fbm(p+1.8*w);
vec3 bg=vec3(.039,.051,.078);vec3 sf=vec3(.075,.094,.141);vec3 deep=mix(bg,k,.25)*vec3(.86,.85,1.);vec3 sky=k;
vec3 c=mix(bg,sf,smoothstep(.2,.75,f));
c=mix(c,deep,smoothstep(.4,.95,length(w)*.95));
c+=sky*.2*smoothstep(.5,.95,f*w.x*1.7);
float calm=smoothstep(.0,.55,distance(uv,vec2(.25,.3)));
c=mix(mix(bg,sf,.55),c,.45+.55*calm);
float vig=smoothstep(1.25,.25,distance(uv,vec2(.45,.6)));
c*=.82+.18*vig;
float gr=h(gl_FragCoord.xy+fract(g)*vec2(91.7,37.3))-.5;
c+=gr*.045;
gl_FragColor=vec4(c,1.);}`;
    const compile = (type, source) => {
      const shader = gl.createShader(type);
      gl.shaderSource(shader, source);
      gl.compileShader(shader);
      if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(shader));
      return shader;
    };
    const program = gl.createProgram();
    gl.attachShader(program, compile(gl.VERTEX_SHADER, vs));
    gl.attachShader(program, compile(gl.FRAGMENT_SHADER, fs));
    gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(program));
    gl.useProgram(program);
    const buffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
    const loc = gl.getAttribLocation(program, "p");
    gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
    const uR = gl.getUniformLocation(program, "r");
    const uT = gl.getUniformLocation(program, "t");
    const uG = gl.getUniformLocation(program, "g");
    const accent = getComputedStyle(document.documentElement).getPropertyValue("--accent-rgb").trim().split(/\s+/).map((v) => Number(v) / 255);
    gl.uniform3fv(gl.getUniformLocation(program, "k"), accent.length === 3 && accent.every((v) => v >= 0) ? accent : [0.227, 0.627, 1]);

    const size = () => {
      const scale = Math.min(devicePixelRatio || 1, 1.5) * 0.75;
      const w = Math.max(1, Math.round(canvas.clientWidth * scale));
      const hgt = Math.max(1, Math.round(canvas.clientHeight * scale));
      if (canvas.width !== w || canvas.height !== hgt) {
        canvas.width = w;
        canvas.height = hgt;
        gl.viewport(0, 0, w, hgt);
      }
    };
    const draw = () => {
      size();
      gl.uniform2f(uR, canvas.width, canvas.height);
      gl.uniform1f(uT, 42);
      gl.uniform1f(uG, 0);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
    };
    new ResizeObserver(draw).observe(canvas);
    draw();
  });
})();
