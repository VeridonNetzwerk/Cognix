export default function ComingSoon({ params }: { params: { route: string[] } }) {
  return (
    <div className="card text-fg-muted">
      <h1 className="text-2xl font-semibold text-fg mb-2">Coming soon</h1>
      <p>This section is reserved for a future release.</p>
    </div>
  );
}
