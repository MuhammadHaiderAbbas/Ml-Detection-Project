import { Link } from "react-router-dom";
import { PageHeader } from "../components/PageHeader";

export function NotFoundPage() {
  return (<><PageHeader title="Page not found" /><p>That page does not exist. <Link to="/">Back to the dashboard</Link>.</p></>);
}
