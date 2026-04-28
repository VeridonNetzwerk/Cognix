"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError } from "@/lib/api";

type Step = 1 | 2 | 3 | 4;

export default function SetupPage() {
  const router = useRouter();
  const [step, setStep] = useState<Step>(1);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  // form
  const [botToken, setBotToken] = useState("");
  const [adminUser, setAdminUser] = useState("");
  const [adminEmail, setAdminEmail] = useState("");
  const [adminPass, setAdminPass] = useState("");
  const [enable2fa, setEnable2fa] = useState(false);
  const [googleClientId, setGoogleClientId] = useState("");
  const [googleClientSecret, setGoogleClientSecret] = useState("");

  // results
  const [otpUri, setOtpUri] = useState<string | null>(null);
  const [otpQr, setOtpQr] = useState<string | null>(null);
  const [backupCodes, setBackupCodes] = useState<string[]>([]);

  useEffect(() => {
    api
      .get<{ configured: boolean }>("/api/v1/setup/status")
      .then((s) => { if (s.configured) router.replace("/login"); })
      .catch(() => {});
  }, [router]);

  async function submitAll() {
    setErr(null);
    setLoading(true);
    try {
      const res = await api.post<{
        otp_provisioning_uri?: string;
        otp_qr_data_url?: string;
        backup_codes?: string[];
      }>("/api/v1/setup/initialize", {
        bot_token: botToken,
        admin_username: adminUser,
        admin_email: adminEmail,
        admin_password: adminPass,
        enable_2fa: enable2fa,
        google_client_id: googleClientId || undefined,
        google_client_secret: googleClientSecret || undefined,
      });
      setOtpUri(res.otp_provisioning_uri ?? null);
      setOtpQr(res.otp_qr_data_url ?? null);
      setBackupCodes(res.backup_codes ?? []);
      setStep(4);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Setup failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center p-6">
      <div className="w-full max-w-2xl space-y-5">
        <h1 className="text-3xl font-semibold">CogniX – First Run Setup</h1>
        <div className="flex gap-2 text-xs text-fg-muted">
          {[1,2,3,4].map((n) => (
            <div key={n} className={"flex-1 rounded-md py-2 text-center " +
              (step >= n ? "bg-brand text-white" : "bg-bg-muted")}>
              Step {n}
            </div>
          ))}
        </div>

        {step === 1 && (
          <div className="card space-y-4">
            <h2 className="text-xl font-medium">1. Discord Bot Token</h2>
            <p className="text-sm text-fg-muted">
              Paste the bot token from the Discord Developer Portal. It will be encrypted at rest.
            </p>
            <input className="input" type="password" placeholder="Bot token"
              value={botToken} onChange={(e) => setBotToken(e.target.value)} />
            <div className="flex justify-end">
              <button className="btn-primary" disabled={!botToken} onClick={() => setStep(2)}>
                Continue
              </button>
            </div>
          </div>
        )}

        {step === 2 && (
          <div className="card space-y-4">
            <h2 className="text-xl font-medium">2. Administrator Account</h2>
            <div className="grid grid-cols-2 gap-3">
              <input className="input" placeholder="Username"
                value={adminUser} onChange={(e) => setAdminUser(e.target.value)} />
              <input className="input" placeholder="Email" type="email"
                value={adminEmail} onChange={(e) => setAdminEmail(e.target.value)} />
            </div>
            <input className="input" placeholder="Password (min 8)" type="password"
              value={adminPass} onChange={(e) => setAdminPass(e.target.value)} />
            <div className="flex justify-between">
              <button className="btn-ghost" onClick={() => setStep(1)}>Back</button>
              <button className="btn-primary"
                disabled={!adminUser || !adminEmail || adminPass.length < 8}
                onClick={() => setStep(3)}>Continue</button>
            </div>
          </div>
        )}

        {step === 3 && (
          <div className="card space-y-4">
            <h2 className="text-xl font-medium">3. Security Options (optional)</h2>
            <label className="flex items-center gap-3">
              <input type="checkbox" checked={enable2fa}
                onChange={(e) => setEnable2fa(e.target.checked)} />
              <span>Enable 2FA (TOTP) for the admin account</span>
            </label>
            <div className="space-y-2">
              <p className="label">Google OAuth (optional)</p>
              <input className="input" placeholder="Client ID"
                value={googleClientId} onChange={(e) => setGoogleClientId(e.target.value)} />
              <input className="input" placeholder="Client Secret" type="password"
                value={googleClientSecret} onChange={(e) => setGoogleClientSecret(e.target.value)} />
            </div>
            {err && <div className="text-danger text-sm">{err}</div>}
            <div className="flex justify-between">
              <button className="btn-ghost" onClick={() => setStep(2)}>Back</button>
              <button className="btn-primary" disabled={loading} onClick={submitAll}>
                {loading ? "Configuring…" : "Finish setup"}
              </button>
            </div>
          </div>
        )}

        {step === 4 && (
          <div className="card space-y-4">
            <h2 className="text-xl font-medium">All set!</h2>
            {otpQr && (
              <div className="space-y-2">
                <p className="label">Scan with your authenticator app</p>
                <img src={otpQr} alt="2FA QR" className="bg-white rounded p-2" width={200} height={200} />
                {otpUri && <code className="block text-xs break-all text-fg-muted">{otpUri}</code>}
              </div>
            )}
            {backupCodes.length > 0 && (
              <div>
                <p className="label">Backup codes (store securely)</p>
                <div className="grid grid-cols-2 gap-2 mt-2">
                  {backupCodes.map((c) => (
                    <code key={c} className="bg-bg-muted rounded px-2 py-1 text-xs">{c}</code>
                  ))}
                </div>
              </div>
            )}
            <button className="btn-primary w-full" onClick={() => router.replace("/login")}>
              Go to login
            </button>
          </div>
        )}
      </div>
    </main>
  );
}
