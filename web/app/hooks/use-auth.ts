"use client";

import { useCallback, useEffect, useState } from "react";
import { API_URL, API_CONFIGURED, parseError, requireApiConfiguration } from "../lib/api";

type AuthState = {
  token: string;
  refreshToken: string;
  isAuthenticated: boolean;
  email: string;
};

/**
 * Authentication hook.
 *
 * Security: access token is kept in memory only (React state) — never
 * persisted to localStorage/sessionStorage. Only the refresh token is
 * stored in localStorage so the session survives page reloads.  On load
 * the hook exchanges the refresh token for a fresh access token.
 */
export function useAuth() {
  const [auth, setAuth] = useState<AuthState>({
    token: "",
    refreshToken: "",
    isAuthenticated: false,
    email: "",
  });
  const [loading, setLoading] = useState(false);
  const [initializing, setInitializing] = useState(true);

  const persistSession = useCallback((accessToken: string, refreshTokenValue: string, emailValue?: string) => {
    setAuth((prev) => ({
      token: accessToken,
      refreshToken: refreshTokenValue,
      isAuthenticated: true,
      email: emailValue ?? prev.email,
    }));
    // Only persist refresh token — access token stays in memory only
    window.localStorage.setItem("dataez_refresh_token", refreshTokenValue);
  }, []);

  const clearSession = useCallback(() => {
    window.localStorage.removeItem("dataez_refresh_token");
    // Clean up legacy key if present
    window.localStorage.removeItem("dataez_token");
    setAuth({ token: "", refreshToken: "", isAuthenticated: false, email: "" });
  }, []);

  const requestNewAccessToken = useCallback(
    async (rt: string): Promise<{ accessToken: string; refreshToken: string } | null> => {
      if (!API_CONFIGURED || !rt) return null;
      const MAX_RETRIES = 3;
      for (let attempt = 0; attempt < MAX_RETRIES; attempt++) {
        try {
          const res = await fetch(`${API_URL}/api/auth/refresh`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ refresh_token: rt }),
          });
          if (res.status >= 400 && res.status < 500) return null;
          if (!res.ok) throw new Error(`refresh failed: ${res.status}`);
          const data = (await res.json()) as { access_token: string; refresh_token: string };
          persistSession(data.access_token, data.refresh_token);
          return { accessToken: data.access_token, refreshToken: data.refresh_token };
        } catch {
          if (attempt < MAX_RETRIES - 1) {
            await new Promise((r) => setTimeout(r, 1000 * 2 ** attempt));
          }
        }
      }
      return null;
    },
    [persistSession]
  );

  const apiFetch = useCallback(
    async (
      path: string,
      init: RequestInit = {},
      authRequired = true,
      accessTokenOverride = ""
    ): Promise<Response> => {
      requireApiConfiguration();
      const headers = new Headers(init.headers || {});
      const accessToken = accessTokenOverride || auth.token;
      if (authRequired && accessToken) {
        headers.set("Authorization", `Bearer ${accessToken}`);
      }
      return fetch(`${API_URL}${path}`, { ...init, headers });
    },
    [auth.token]
  );

  const apiFetchWithRefresh = useCallback(
    async (path: string, init: RequestInit = {}): Promise<Response> => {
      let res = await apiFetch(path, init, true);
      if (res.status !== 401) return res;

      const refreshed = await requestNewAccessToken(auth.refreshToken);
      if (!refreshed) {
        clearSession();
        return res;
      }
      res = await apiFetch(path, init, true, refreshed.accessToken);
      return res;
    },
    [apiFetch, auth.refreshToken, requestNewAccessToken, clearSession]
  );

  const login = useCallback(
    async (email: string, password: string): Promise<void> => {
      requireApiConfiguration();
      setLoading(true);
      try {
        const res = await fetch(`${API_URL}/api/auth/login`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email: email.trim(), password }),
        });
        if (!res.ok) throw new Error(await parseError(res));
        const data = (await res.json()) as { access_token: string; refresh_token: string };
        persistSession(data.access_token, data.refresh_token);
      } finally {
        setLoading(false);
      }
    },
    [persistSession]
  );

  const signup = useCallback(
    async (email: string, password: string, name: string): Promise<void> => {
      requireApiConfiguration();
      setLoading(true);
      try {
        const res = await fetch(`${API_URL}/api/auth/signup`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email: email.trim(), password, name: name.trim() }),
        });
        if (!res.ok) throw new Error(await parseError(res));
        const data = (await res.json()) as { access_token: string; refresh_token: string };
        persistSession(data.access_token, data.refresh_token);
      } finally {
        setLoading(false);
      }
    },
    [persistSession]
  );

  const logout = useCallback(async () => {
    try {
      if (API_CONFIGURED && auth.refreshToken) {
        await fetch(`${API_URL}/api/auth/logout`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ refresh_token: auth.refreshToken }),
        });
      }
    } catch {
      // ignore
    }
    clearSession();
  }, [auth.refreshToken, clearSession]);

  // On mount: restore session from refresh token only
  useEffect(() => {
    if (!API_CONFIGURED) {
      setInitializing(false);
      return;
    }
    const storedRefresh = window.localStorage.getItem("dataez_refresh_token") || "";
    // Clean up legacy access token key if present
    window.localStorage.removeItem("dataez_token");

    if (!storedRefresh) {
      setInitializing(false);
      return;
    }

    (async () => {
      try {
        // Always exchange refresh token for a fresh access token
        const refreshed = await requestNewAccessToken(storedRefresh);
        if (!refreshed) {
          clearSession();
        } else {
          // Fetch user info with the fresh access token
          const res = await fetch(`${API_URL}/api/auth/me`, {
            headers: { Authorization: `Bearer ${refreshed.accessToken}` },
          });
          if (res.ok) {
            const meData = (await res.json()) as { email?: string };
            setAuth((prev) => ({ ...prev, email: meData.email || "" }));
          }
        }
      } catch {
        clearSession();
      } finally {
        setInitializing(false);
      }
    })();
  }, []);

  return {
    token: auth.token,
    email: auth.email,
    isAuthenticated: auth.isAuthenticated,
    loading,
    initializing,
    login,
    signup,
    logout,
    apiFetch,
    apiFetchWithRefresh,
  };
}
