import { Link } from "wouter";
import { Shell } from "@/components/Shell";

export default function NotFound() {
  return (
    <Shell>
      <main className="crash glass panel">
        <h1 className="heading">Page not found</h1>
        <p className="body" style={{ margin: 0 }}>There is no page at this address.</p>
        <div><Link href="/" className="btn fill">Back to Home</Link></div>
      </main>
    </Shell>
  );
}
