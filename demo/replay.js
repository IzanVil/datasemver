// The dashboard as it ships, without its server: every request it makes is answered from a
// comparison recorded against the real backend. Only the recorded inputs can be replayed, so
// anything else gets an answer that says so instead of a report about other files.
(() => {
  const base = new URL("./data/", document.currentScript.src);
  const embedded = new URLSearchParams(location.search).has("embed");
  if (embedded) document.documentElement.classList.add("is-embed");

  // The dashboard brings its report into view after a comparison. Inside the project site that
  // must not move the page around the frame, and the comparison run on arrival is not one the
  // visitor asked for, so it does not scroll anywhere.
  const scrollIntoView = Element.prototype.scrollIntoView;
  let arrived = false;
  Element.prototype.scrollIntoView = function (options) {
    if (!arrived) {
      arrived = true;
      return;
    }
    if (window.top === window) return scrollIntoView.call(this, options);
    window.scrollTo({ top: this.getBoundingClientRect().top + window.scrollY, behavior: "smooth" });
  };

  const SAMPLE = { old: "old.csv", new: "new.csv", version: "1.4.2" };
  const HISTORY = {
    "customers 1 2": "history-customers-1-2.json",
    "customers 2 3": "history-customers-2-3.json",
    "customers 1 3": "history-customers-1-3.json",
    "users 1 2": "history-users-1-2.json",
  };
  const LOCAL = 'pip install "datasemver[web]"';

  const realFetch = window.fetch.bind(window);
  const texts = {};
  const sample = (name) => (texts[name] ??= realFetch(new URL(name, base)).then((r) => r.text()));

  const reply = (body, status = 200) =>
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    });
  const recorded = async (name) => reply(await (await realFetch(new URL(name, base))).json());
  const refuse = (detail) => reply({ detail }, 422);

  async function isSample(file, name) {
    return file instanceof File && file.size > 0 && (await file.text()) === (await sample(name));
  }

  async function diff(form) {
    const plain =
      (await isSample(form.get("old"), SAMPLE.old)) &&
      (await isSample(form.get("new"), SAMPLE.new)) &&
      form.get("current_version") === SAMPLE.version &&
      !form.get("key") &&
      !(form.get("rules") instanceof File && form.get("rules").size > 0);
    if (!plain) {
      return refuse(
        "This page replays one recorded comparison: the two sample files at 1.4.2, " +
          `with no key and the default rules. To compare your own files, run ${LOCAL}.`
      );
    }
    return recorded("diff.json");
  }

  async function profile(form) {
    if (await isSample(form.get("dataset"), SAMPLE.new)) return recorded("profile.json");
    return refuse(`This page holds the profile of the sample's new version only. Run ${LOCAL} for yours.`);
  }

  window.fetch = async (input, options = {}) => {
    const url = new URL(typeof input === "string" ? input : input.url, location.origin);
    if (!url.pathname.startsWith("/api/")) return realFetch(input, options);
    await new Promise((resolve) => setTimeout(resolve, 260));

    const path = url.pathname;
    if (path === "/api/meta") return recorded("meta.json");
    if (path === "/api/diff") return diff(options.body);
    if (path === "/api/profile") return profile(options.body);
    if (path === "/api/history") return recorded("history.json");
    const match = path.match(/^\/api\/history\/([^/]+)\/diff$/);
    if (match) {
      const key = `${decodeURIComponent(match[1])} ${url.searchParams.get("old")} ${url.searchParams.get("new")}`;
      if (HISTORY[key]) return recorded(HISTORY[key]);
      return refuse(`This pair was not recorded. The replay holds ${Object.keys(HISTORY).length} of them; run ${LOCAL} for the rest.`);
    }
    return refuse("Not part of the replay.");
  };

  // The sample is chosen and compared on arrival, so the report is what the page opens on.
  window.addEventListener("DOMContentLoaded", async () => {
    const form = document.getElementById("compare-form");
    const put = async (side, name) => {
      const input = form.querySelector(`input[name="${side}"]`);
      const transfer = new DataTransfer();
      transfer.items.add(new File([await sample(name)], name, { type: "text/csv" }));
      input.files = transfer.files;
      input.dispatchEvent(new Event("change"));
    };
    await put("old", SAMPLE.old);
    await put("new", SAMPLE.new);
    form.querySelector('input[name="current_version"]').value = SAMPLE.version;
    form.requestSubmit();
  });
})();
