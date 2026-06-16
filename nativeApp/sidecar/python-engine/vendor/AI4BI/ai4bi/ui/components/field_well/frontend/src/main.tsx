import React from "react";
import ReactDOM from "react-dom/client";
import { withStreamlitConnection } from "streamlit-component-lib";
import FieldWell from "./FieldWell";

// Wrap the component so it speaks the Streamlit <-> iframe protocol
// (render args in, setComponentValue out, theme + frame height).
const Connected = withStreamlitConnection(FieldWell);

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <Connected />
  </React.StrictMode>
);
