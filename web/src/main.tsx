// The style files in the old page's order: its own style, then each panel's.
import "../styles/page.css";
import "../styles/contributions.css";
import "../styles/responsive.css";
import "../styles/queue.css";
import "../styles/variable-workspace.css";
import "../styles/filter-picker.css";
import "../styles/workspaces.css";
import "../styles/sector-view.css";
import { render } from "preact";
import { Shell } from "./shell/Shell.tsx";

render(<Shell />, document.body);
