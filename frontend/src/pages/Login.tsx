import { useEffect, useState } from "react";
import { useAuth } from "../auth/AuthProvider";
import { isAuthDisabled } from "../api/client";

export default function Login() {
  const { login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (isAuthDisabled) {
      window.location.href = "/";
    }
  }, []);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      await login(email, password);
      window.location.href = "/";
    } catch (e: any) {
      setErr(e?.response?.data?.detail || "Login failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <style>{`
        .login-container {
          min-height: 100vh;
          display: flex;
          align-items: center;
          justify-content: center;
          background: linear-gradient(135deg, #1e3a8a 0%, #1e40af 50%, #2563eb 100%);
          padding: 2rem 1rem;
        }

        .login-card {
          background: white;
          border-radius: 16px;
          box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
          width: 100%;
          max-width: 440px;
          overflow: hidden;
        }

        .login-header {
          background: linear-gradient(to bottom, #f8f9fa, white);
          padding: 3rem 2.5rem 2rem;
          text-align: center;
          border-bottom: 1px solid #e5e7eb;
        }

        .login-logo {
          width: 64px;
          height: 64px;
          background: linear-gradient(135deg, #1e3a8a, #2563eb);
          border-radius: 16px;
          margin: 0 auto 1.5rem;
          display: flex;
          align-items: center;
          justify-content: center;
          box-shadow: 0 4px 12px rgba(37, 99, 235, 0.2);
        }

        .login-logo-text {
          color: white;
          font-size: 1.75rem;
          font-weight: 700;
          letter-spacing: -0.02em;
        }

        .login-title {
          font-size: 1.875rem;
          font-weight: 700;
          color: #111827;
          margin: 0 0 0.5rem 0;
          letter-spacing: -0.02em;
        }

        .login-subtitle {
          font-size: 0.9375rem;
          color: #6b7280;
          margin: 0;
          font-weight: 400;
        }

        .login-form {
          padding: 2.5rem;
        }

        .login-field {
          margin-bottom: 1.75rem;
        }

        .login-label {
          display: block;
          font-size: 0.8125rem;
          font-weight: 600;
          color: #374151;
          margin-bottom: 0.5rem;
          text-transform: uppercase;
          letter-spacing: 0.05em;
        }

        .login-input {
          width: 100%;
          padding: 0.875rem 1rem;
          border: 2px solid #d1d5db;
          border-radius: 8px;
          font-size: 0.9375rem;
          color: #111827;
          transition: all 0.2s ease;
          background: white;
        }

        .login-input:focus {
          outline: none;
          border-color: #2563eb;
          box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.1);
        }

        .login-input::placeholder {
          color: #9ca3af;
        }

        .login-error {
          background: #fef2f2;
          border: 1px solid #fecaca;
          color: #991b1b;
          padding: 0.875rem 1rem;
          border-radius: 8px;
          font-size: 0.875rem;
          margin-bottom: 1.5rem;
          display: flex;
          align-items: center;
          gap: 0.5rem;
        }

        .login-error-icon {
          flex-shrink: 0;
        }

        .login-button {
          width: 100%;
          padding: 0.875rem 1.5rem;
          background: linear-gradient(135deg, #1e3a8a, #2563eb);
          color: white;
          border: none;
          border-radius: 8px;
          font-size: 0.9375rem;
          font-weight: 600;
          cursor: pointer;
          transition: all 0.2s ease;
          box-shadow: 0 4px 12px rgba(37, 99, 235, 0.2);
          letter-spacing: 0.02em;
        }

        .login-button:hover:not(:disabled) {
          background: linear-gradient(135deg, #1e40af, #1d4ed8);
          box-shadow: 0 6px 16px rgba(37, 99, 235, 0.3);
          transform: translateY(-1px);
        }

        .login-button:active:not(:disabled) {
          transform: translateY(0);
        }

        .login-button:disabled {
          opacity: 0.6;
          cursor: not-allowed;
          transform: none;
        }

        .login-footer {
          padding: 1.5rem 2.5rem;
          background: #f8f9fa;
          border-top: 1px solid #e5e7eb;
          text-align: center;
        }

        .login-footer-text {
          font-size: 0.8125rem;
          color: #6b7280;
          margin: 0;
          line-height: 1.6;
        }

        .dev-badge {
          display: inline-block;
          background: #fef3c7;
          color: #92400e;
          padding: 0.25rem 0.625rem;
          border-radius: 4px;
          font-size: 0.75rem;
          font-weight: 600;
          margin-top: 0.5rem;
        }

        @keyframes fadeIn {
          from {
            opacity: 0;
            transform: translateY(10px);
          }
          to {
            opacity: 1;
            transform: translateY(0);
          }
        }

        .login-card {
          animation: fadeIn 0.4s ease-out;
        }

        @media (max-width: 480px) {
          .login-header {
            padding: 2rem 1.5rem 1.5rem;
          }
          
          .login-form {
            padding: 2rem 1.5rem;
          }
          
          .login-footer {
            padding: 1.25rem 1.5rem;
          }
          
          .login-title {
            font-size: 1.5rem;
          }
        }
      `}</style>

      <div className="login-container">
        <div className="login-card">
          <div className="login-header">
            <div className="login-logo">
              <span className="login-logo-text">T</span>
            </div>
            <h1 className="login-title">Welcome Back</h1>
            <p className="login-subtitle">Sign in to access your timecard</p>
          </div>

          <form onSubmit={onSubmit} className="login-form">
            <div className="login-field">
              <label className="login-label">Email Address</label>
              <input
                type="email"
                className="login-input"
                placeholder="you@company.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                autoComplete="email"
                required
              />
            </div>

            <div className="login-field">
              <label className="login-label">Password</label>
              <input
                type="password"
                className="login-input"
                placeholder="Enter your password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                required
              />
            </div>

            {err && (
              <div className="login-error">
                <svg
                  className="login-error-icon"
                  width="20"
                  height="20"
                  viewBox="0 0 20 20"
                  fill="currentColor"
                >
                  <path
                    fillRule="evenodd"
                    d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z"
                    clipRule="evenodd"
                  />
                </svg>
                {err}
              </div>
            )}

            <button type="submit" disabled={busy} className="login-button">
              {busy ? "Signing in..." : "Sign In"}
            </button>
          </form>

          <div className="login-footer">
            <p className="login-footer-text">
              {isAuthDisabled ? (
                <>
                  <span className="dev-badge">DEV MODE</span>
                  <br />
                  Authentication is disabled. Redirecting to app...
                </>
              ) : (
                "Secure authentication powered by JWT"
              )}
            </p>
          </div>
        </div>
      </div>
    </>
  );
}