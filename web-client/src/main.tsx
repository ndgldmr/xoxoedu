import React from "react";
import ReactDOM from "react-dom/client";

import "@fontsource/geist/400.css";
import "@fontsource/geist/500.css";
import "@fontsource/geist/600.css";
import "@fontsource/geist-mono/400.css";
import {AppProviders} from "./app/AppProviders";
import {browserRouter} from "./routes/router";
import "./styles/globals.css";

const rootElement = document.getElementById("root");

if (!rootElement) {
  throw new Error("Missing #root mount point.");
}

ReactDOM.createRoot(rootElement).render(
  <React.StrictMode>
    <AppProviders router={browserRouter} />
  </React.StrictMode>,
);
