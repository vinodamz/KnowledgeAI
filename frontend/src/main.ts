import { bootstrapApplication } from "@angular/platform-browser";
import { provideRouter } from "@angular/router";
import { App } from "./app/app";
import { Profiles } from "./app/profiles/profiles";
import { Models } from "./app/models/models";
import { Review } from "./app/review/review";
import { GraphPage } from "./app/graph/graph";
import { Ask } from "./app/ask/ask";
import { ActivityPage } from "./app/activity/activity";
bootstrapApplication(App, {
  providers: [
    provideRouter([
      { path: "profiles", component: Profiles },
      { path: "profiles/:id/versions", component: Profiles },
      { path: "models", component: Models },
      { path: "review", component: Review },
      { path: "graph", component: GraphPage },
      { path: "ask", component: Ask },
      { path: "activity", component: ActivityPage },
      { path: "**", redirectTo: "profiles" },
    ]),
  ],
}).catch(console.error);
