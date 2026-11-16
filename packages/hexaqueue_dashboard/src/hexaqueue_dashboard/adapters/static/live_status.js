(() => {
    if (window.__hqLivePingStarted) {
        return;
    }
    window.__hqLivePingStarted = true;

    const formatTime = (date) => {
        const pad = (n) => String(n).padStart(2, "0");
        return `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
    };

    let lastUpdateStr = formatTime(new Date());

    const setBadge = (state, timestampStr) => {
        const badge = document.getElementById("hq-live-badge");
        const dot = document.getElementById("hq-live-dot");
        const text = document.getElementById("hq-live-text");
        if (!badge || !dot || !text) {
            return;
        }
        const tunnelOnly = badge.dataset && badge.dataset.mode === "tunnel";
        if (tunnelOnly) {
            if (state === "disconnected") {
                badge.style.backgroundColor = "#b91c1c";
                dot.style.backgroundColor = "#fca5a5";
                text.textContent = "Tunnel Disconnected";
            } else {
                badge.style.backgroundColor = "#15803d";
                dot.style.backgroundColor = "#86efac";
                text.textContent = "Tunnel Connected";
            }
            return;
        }
        if (state === "updated") {
            lastUpdateStr = timestampStr || formatTime(new Date());
            badge.style.backgroundColor = "#15803d";
            dot.style.backgroundColor = "#86efac";
            text.textContent = `Connected · Updated ${lastUpdateStr}`;
        } else if (state === "idle") {
            badge.style.backgroundColor = "#15803d";
            dot.style.backgroundColor = "#86efac";
            text.textContent = `Connected · Idle (Last: ${lastUpdateStr})`;
        } else {
            badge.style.backgroundColor = "#b91c1c";
            dot.style.backgroundColor = "#fca5a5";
            text.textContent = `Disconnected (Last: ${lastUpdateStr})`;
        }
    };

    const pingHealth = async () => {
        try {
            const controller = new AbortController();
            const timer = setTimeout(() => controller.abort(), 2500);
            const resp = await fetch("/dashboard/health", {
                cache: "no-store",
                signal: controller.signal,
            });
            clearTimeout(timer);
            if (resp.ok) {
                setBadge("idle");
                return true;
            }
            setBadge("disconnected");
            return false;
        } catch (_err) {
            setBadge("disconnected");
            return false;
        }
    };

    window.addEventListener("hq:cluster-update", (ev) => {
        const changed = Boolean(ev && ev.detail && ev.detail.changed);
        if (changed) {
            setBadge("updated", formatTime(new Date()));
        } else {
            setBadge("idle");
        }
    });

    const badgeEl = document.getElementById("hq-live-badge");
    const isTunnelOnly = Boolean(
        badgeEl && badgeEl.dataset && badgeEl.dataset.mode === "tunnel"
    );

    if (!isTunnelOnly && typeof window.EventSource === "function") {
        try {
            const es = new window.EventSource("/dashboard/events");
            es.addEventListener("snapshot", () => setBadge("updated", formatTime(new Date())));
            es.addEventListener("cluster_update", () => setBadge("updated", formatTime(new Date())));
            es.addEventListener("heartbeat", () => setBadge("idle"));
            es.onerror = () => {
                void pingHealth();
            };
        } catch (_err) {
            void pingHealth();
        }
    }

    void pingHealth();
    setInterval(() => {
        void pingHealth();
    }, 5000);
})();
