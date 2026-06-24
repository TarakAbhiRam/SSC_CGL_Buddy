/**
 * Transport Adapter Layer
 * 
 * Abstracts the communication channel (PyWebView for desktop, HTTP for Android)
 * behind a single interface. The frontend imports and uses this instead of
 * directly calling window.pywebview.api.
 * 
 * Usage: const result = await transport.call('start_quiz', options);
 */

class TransportAdapter {
  constructor() {
    this.bridge = null;
    this.ready = false;
  }

  /**
   * Initialize the transport bridge.
   * On desktop: waits for PyWebView injection and wraps it.
   * On Android: creates HTTP bridge to local backend.
   */
  async init() {
    // Attempt PyWebView bridge first (desktop)
    const pywebviewBridge = await this._initPyWebViewBridge();
    if (pywebviewBridge) {
      this.bridge = pywebviewBridge;
      this.ready = true;
      console.log('[Transport] PyWebView bridge initialized (desktop)');
      return;
    }

    // Fallback to HTTP bridge (Android or if PyWebView unavailable)
    const httpBridge = this._initHTTPBridge();
    this.bridge = httpBridge;
    this.ready = true;
    console.log('[Transport] HTTP bridge initialized (Android or dev mode)');
  }

  /**
   * Attempt to initialize PyWebView bridge.
   * Returns null if PyWebView is not available.
   */
  _initPyWebViewBridge() {
    return new Promise((resolve) => {
      const timeout = setTimeout(() => resolve(null), 2000);
      
      const checkApi = () => {
        if (window.pywebview && window.pywebview.api) {
          clearTimeout(timeout);
          resolve(new PyWebViewBridge(window.pywebview.api));
        }
      };

      // Try immediately in case already injected
      checkApi();

      // Listen for pywebviewready event
      window.addEventListener('pywebviewready', checkApi, { once: true });

      // Poll as fallback
      const pollInterval = setInterval(() => {
        checkApi();
        if (window.pywebview && window.pywebview.api) {
          clearInterval(pollInterval);
        }
      }, 100);
    });
  }

  /**
   * Initialize HTTP bridge for local backend.
   * Used on Android (Capacitor) or when PyWebView is unavailable.
   */
  _initHTTPBridge() {
    const baseUrl = window.__API_BASE_URL__ || 'http://localhost:8000/api';
    const httpBridge = new HTTPBridge(baseUrl);
    if (window.CglBuddyAndroid) {
      return new AndroidBridge(httpBridge, window.CglBuddyAndroid);
    }
    return httpBridge;
  }

  /**
   * Unified call interface.
   * Forwards to the active bridge (PyWebView or HTTP).
   */
  async call(method, ...args) {
    if (!this.ready) {
      throw new Error('Transport not initialized. Call await transport.init() first.');
    }
    return this.bridge.call(method, ...args);
  }

  /**
   * Async call with retry (for flaky network scenarios on Android).
   */
  async callWithRetry(method, args, maxRetries = 3) {
    let lastError;
    for (let i = 0; i < maxRetries; i++) {
      try {
        return await this.call(method, args);
      } catch (e) {
        lastError = e;
        if (i < maxRetries - 1) {
          await new Promise(r => setTimeout(r, 100 * Math.pow(2, i)));
        }
      }
    }
    throw lastError;
  }
}

/**
 * PyWebView Bridge
 * Wraps window.pywebview.api for desktop (Windows/macOS).
 */
class PyWebViewBridge {
  constructor(api) {
    this.api = api;
  }

  async call(method, ...args) {
    if (typeof this.api[method] !== 'function') {
      throw new Error(`Method not found on PyWebView API: ${method}`);
    }
    return this.api[method](...args);
  }
}

/**
 * Android Bridge
 * Uses the native Android host only for sandboxed file picking; normal backend
 * calls still go through the HTTP bridge so the API contract stays shared.
 */
class AndroidBridge {
  constructor(httpBridge, nativeBridge) {
    this.httpBridge = httpBridge;
    this.nativeBridge = nativeBridge;
    this.pendingFiles = new Map();
    window.__androidFileResult = (callbackId, path) => {
      const pending = this.pendingFiles.get(callbackId);
      if (!pending) return;
      this.pendingFiles.delete(callbackId);
      pending(path || null);
    };
  }

  async call(method, ...args) {
    if (method === 'pick_pdf') return this._pickFile('pdf');
    if (method === 'pick_import_file') return this._pickFile('image');
    if (method === 'pick_database_import_file') return this._pickFile('database');
    return this.httpBridge.call(method, ...args);
  }

  _pickFile(kind) {
    return new Promise((resolve) => {
      const callbackId = `${kind}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
      this.pendingFiles.set(callbackId, resolve);
      this.nativeBridge.pickFile(kind, callbackId);
    });
  }
}

/**
 * HTTP Bridge
 * Calls local HTTP backend for Android (Capacitor) or dev/test.
 */
class HTTPBridge {
  constructor(baseUrl) {
    this.baseUrl = baseUrl;
  }

  _payloadFor(method, args) {
    if (args.length === 0) return {};
    if (args.length === 1 && typeof args[0] === 'object' && !Array.isArray(args[0])) {
      return args[0];
    }

    switch (method) {
      case 'test_api_key':
        return { provider: args[0], api_key: args[1] };
      case 'delete_api_key':
        return { provider: args[0] };
      case 'list_topics':
        return { subject: args[0] };
      case 'bank_count':
        return { category: args[0], difficulty: args[1], topics: args[2] };
      case 'submit_quiz':
        return { quiz_id: args[0], responses: args[1] };
      case 'save_ai_questions':
        return { quiz_id: args[0] };
      case 'list_db_questions':
        return { subject: args[0], source: args[1] };
      case 'delete_db_question':
        return { question_id: args[0] };
      case 'delete_db_source':
        return { source: args[0] };
      case 'import_questions':
        return { file_path: args[0], options: args[1] || {} };
      case 'import_database':
        return { file_path: args[0] };
      default:
        if (args.length === 1) {
          return { value: args[0] };
        }
        return { args };
    }
  }

  async call(method, ...args) {
    // Map method name to HTTP endpoint
    // Standard convention: POST /api/{method}
    const endpoint = `${this.baseUrl}/${method}`;

    const body = this._payloadFor(method, args);

    try {
      const response = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`HTTP ${response.status}: ${errorText}`);
      }

      return await response.json();
    } catch (error) {
      console.error(`[HTTPBridge] Error calling ${method}:`, error);
      throw error;
    }
  }
}

// Singleton instance
const transport = new TransportAdapter();
