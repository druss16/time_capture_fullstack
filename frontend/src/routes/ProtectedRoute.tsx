import { Navigate } from "react-router-dom";
import { useAuth } from "../auth/AuthProvider";

export default function ProtectedRoute({ children }: { children: JSX.Element }) {
  const { isAuthed, loading } = useAuth();
  if (loading) return <div className="p-6">Loading…</div>;
  if (!isAuthed) return <Navigate to="/login" replace />;
  return children;
}
