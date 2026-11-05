// The launcher opens this page with the app key in the fragment, which the
      // browser never sends to a server. It is taken out of the address bar at
      // once, kept in memory, and attached to same-origin API calls — so every
      // fetch in the app carries it without any of them having to know it
      // exists. Reads of your conversations are refused without it, because
      // loopback is reachable by every account on this machine.
      (function () {
        const STORE = 'agentTraceKey';
        let key = '';

        function takeKeyFromHash() {
          const found = /(?:^|[#&])k=([^&]+)/.exec(location.hash || '');
          if (!found) return false;
          key = decodeURIComponent(found[1]);
          window.__agentTraceKey = key;
          try {
            // Kept per origin, so a reload or a bookmark still works; the only
            // page on this origin is this app.
            sessionStorage.setItem(STORE, key);
          } catch (_) { /* private mode: the in-memory copy still works */ }
          try { history.replaceState(null, '', location.pathname + location.search); } catch (_) {}
          return true;
        }

        if (!takeKeyFromHash()) {
          try { key = sessionStorage.getItem(STORE) || ''; } catch (_) { key = ''; }
        }
        window.__agentTraceKey = key;

        // Pasting the launcher's address into a tab that is already open changes
        // only the fragment, which is a same-document navigation: nothing
        // reloads. Without this the key would be sitting in the address bar
        // while the app went on claiming it had none.
        window.addEventListener('hashchange', function () {
          if (takeKeyFromHash()) {
            const notice = document.getElementById('agent-trace-key-notice');
            if (notice) notice.remove();
            location.reload();
          }
        });

        function refused(why) {
          if (document.getElementById('agent-trace-key-notice')) return;
          const notice = document.createElement('div');
          notice.id = 'agent-trace-key-notice';
          notice.style.cssText = 'position:fixed;z-index:99999;left:50%;top:18px;transform:translateX(-50%);'
            + 'padding:10px 16px;border-radius:8px;font:13px/1.5 ui-sans-serif,system-ui;'
            + 'background:#3b1d1d;color:#ffd9d9;border:1px solid #7d3a3a;max-width:70ch';
          notice.textContent = why;
          (document.body || document.documentElement).appendChild(notice);
        }

        const inner = window.fetch.bind(window);
        window.fetch = function (input, init) {
          const url = typeof input === 'string' ? input : (input && input.url) || '';
          const sameOrigin = new URL(url, location.href).origin === location.origin;
          if (!sameOrigin) return inner(input, init);
          const next = Object.assign({}, init || {});
          const headers = new Headers((next.headers) || (typeof input === 'object' && input.headers) || {});
          if (key) headers.set('X-Agent-Trace-Key', key);
          next.headers = headers;
          return inner(input, next).then(function (response) {
            // A stale or absent key otherwise shows up as an app that loads and
            // then stays empty, which reads as a broken app rather than a
            // locked one.
            if (response && response.status === 401) {
              try { sessionStorage.removeItem(STORE); } catch (_) {}
              refused('Agent Trace could not read your conversations: this page is not carrying the app key. '
                + 'Reopen it from the launcher (or run the server with --rotate-key and use the address it prints).');
            }
            return response;
          });
        };
      })();
