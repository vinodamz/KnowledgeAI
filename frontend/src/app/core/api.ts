import { Injectable, signal } from "@angular/core";
import { Actor, Profile, Version, Context, Schema } from "./contracts";
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}
@Injectable({ providedIn: "root" })
export class Api {
  actor = signal<Actor | null>(null);
  ready = signal(false);
  error = signal("");
  notice = signal("");
  busy = signal(false);
  profiles = signal<Profile[]>([]);
  versions = signal<Version[]>([]);
  contexts = signal<Context[]>([]);
  profileId = signal(sessionStorage.getItem("ka-profile") || "");
  versionId = signal(sessionStorage.getItem("ka-version") || "");
  scopeLoading = signal(false);
  private scopeRequest = 0;
  private pendingActions = 0;
  private csrf = "";
  get profile() {
    return this.profiles().find((p) => p.id === this.profileId());
  }
  get version() {
    return this.versions().find((v) => v.id === this.versionId());
  }
  get isAdmin() {
    return this.actor()?.role === "admin";
  }
  get canOwn() {
    return (
      !this.scopeLoading() &&
      !!this.profile &&
      this.profile.owner_id === this.actor()?.id &&
      ["owner", "admin"].includes(this.actor()?.role || "")
    );
  }
  get canEdit() {
    return (
      !this.scopeLoading() &&
      (this.isAdmin ||
        this.canOwn ||
        !!this.actor()?.contribute_profile_ids.includes(this.profileId()))
    );
  }
  async request<T>(path: string, method = "GET", body?: unknown): Promise<T> {
    if (method !== "GET" && !path.startsWith("/auth/") && this.scopeLoading())
      throw new Error(
        "Wait for the selected profile to finish loading before making changes.",
      );
    const headers: Record<string, string> = {};
    if (body !== undefined && !(body instanceof FormData))
      headers["Content-Type"] = "application/json";
    if (method !== "GET") headers["X-CSRF-Token"] = this.csrf;
    const r = await fetch("/api" + path, {
      method,
      credentials: "same-origin",
      headers,
      body:
        body === undefined
          ? undefined
          : body instanceof FormData
            ? body
            : JSON.stringify(body),
    });
    if (!r.ok) {
      const data = await r.json().catch(() => ({ detail: "Request failed" }));
      if (r.status === 401) this.actor.set(null);
      throw new ApiError(
        r.status,
        typeof data.detail === "string"
          ? data.detail
          : JSON.stringify(data.detail),
      );
    }
    return (r.status === 204 ? undefined : await r.json()) as T;
  }
  async run(action: () => Promise<void>, clearFeedback = true) {
    if (clearFeedback) {
      this.error.set("");
      this.notice.set("");
    }
    this.pendingActions++;
    this.busy.set(true);
    try {
      await action();
    } catch (e) {
      this.error.set(
        e instanceof ApiError && e.status === 409
          ? e.message +
              " Your view has not been overwritten. Refresh and compare before trying again."
          : e instanceof Error
            ? e.message
            : "Unable to complete request",
      );
    } finally {
      this.pendingActions--;
      this.busy.set(this.pendingActions > 0);
    }
  }
  async init() {
    try {
      this.actor.set(await this.request<Actor>("/auth/me"));
      this.csrf = (
        await this.request<{ csrf_token: string }>("/auth/csrf")
      ).csrf_token;
      await this.reload();
    } catch (e) {
      if (!(e instanceof ApiError && e.status === 401))
        this.error.set(String(e));
    } finally {
      this.ready.set(true);
    }
  }
  async login(username: string, password: string) {
    const body: Schema<"Credentials"> = { username, password };
    const r = await this.request<{ csrf_token: string }>(
      "/auth/login",
      "POST",
      body,
    );
    this.csrf = r.csrf_token;
    this.actor.set(await this.request<Actor>("/auth/me"));
    await this.reload();
  }
  async logout() {
    await this.request("/auth/logout", "POST");
    this.actor.set(null);
    this.csrf = "";
    this.profiles.set([]);
    this.versions.set([]);
    this.contexts.set([]);
  }
  async reload() {
    this.profiles.set(await this.request<Profile[]>("/profiles"));
    this.contexts.set(await this.request<Context[]>("/available-contexts"));
    const id = this.profiles().some((p) => p.id === this.profileId())
      ? this.profileId()
      : this.profiles()[0]?.id || "";
    await this.selectProfile(id);
  }
  async selectProfile(id: string) {
    const request = ++this.scopeRequest;
    const previousVersion = this.profileId() === id ? this.versionId() : "";
    this.scopeLoading.set(true);
    this.selectVersion("");
    this.versions.set([]);
    this.profileId.set(id);
    sessionStorage.setItem("ka-profile", id);
    try {
      const versions = id
        ? await this.request<Version[]>(`/profiles/${id}/versions`)
        : [];
      if (request !== this.scopeRequest || id !== this.profileId()) return;
      this.versions.set(versions);
      this.selectVersion(
        versions.some((v) => v.id === previousVersion)
          ? previousVersion
          : versions[0]?.id || "",
      );
    } catch (error) {
      if (request === this.scopeRequest) throw error;
    } finally {
      if (request === this.scopeRequest) this.scopeLoading.set(false);
    }
  }

  selectVersion(id: string) {
    if (
      id &&
      !this.versions().some(
        (v) => v.id === id && v.profile_id === this.profileId(),
      )
    )
      return;
    this.versionId.set(id);
    sessionStorage.setItem("ka-version", id);
  }
}
