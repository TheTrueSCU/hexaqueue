(() => {
    if (window.__hqLivePingStarted) {
        return;
    }
    window.__hqLivePingStarted = true;

    const updateBadge = (live) => {
        const badge = document.getElementById("hq-live-badge");
        const dot = document.getElementById("hq-live-dot");
        const text = document.getElementById("hq-live-text");
        if (!badge || !dot || !text) {
            return;
        }
        if (live) {
            badge.style.backgroundColor = "#15803d";
            dot.style.backgroundColor = "#86efac";
            text.textContent = "Live";
        } else {
            badge.style.backgroundColor = "#b91c1c";
            dot.style.backgroundColor = "#fca5a5";
            text.textContent = "Tunnel Disconnected";
        }
    };

    const pingHost = async () => {
        try {
            const controller = new AbortController();
            const timer = setTimeout(() => controller.abort(), 2500);
            const resp = await fetch("/dashboard/health", {
                cache: "no-store",
                signal: controller.signal,
            });
            clearTimeout(timer);
            updateBadge(resp.ok);
        } catch (_err) {
            updateBadge(false);
        }
    };

    pingHost();
    setInterval(pingHost, 5000);
})();
