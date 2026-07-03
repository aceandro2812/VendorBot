import React, { useState, useEffect } from 'react';
import './App.css';

const API_BASE = 'http://localhost:8000/api';
const MAX_NEGOTIATION_TURNS = 4;

export default function App() {
  const [sessions, setSessions] = useState([]);
  const [selectedSessionId, setSelectedSessionId] = useState('');
  const [currentSession, setCurrentSession] = useState(null);
  const [loading, setLoading] = useState(false);
  // All models currently available on the Gemini API Free Tier (as of Jul 2026)
  const GEMINI_FREE_TIER_MODELS = [
    // --- Generation 3.x (Latest) ---
    { value: 'gemini-3.5-flash',      label: 'Gemini 3.5 Flash',      badge: 'NEW',        desc: 'Current standard high-performance model' },
    { value: 'gemini-3.1-flash-lite', label: 'Gemini 3.1 Flash-Lite', badge: 'NEW LITE',   desc: 'Latest high-volume, ultra-low latency' },
    // --- Generation 2.5 ---
    { value: 'gemini-2.5-flash',      label: 'Gemini 2.5 Flash',      badge: 'DEFAULT',    desc: 'Best 2.5 price/performance balance' },
    { value: 'gemini-2.5-flash-lite', label: 'Gemini 2.5 Flash-Lite', badge: 'FAST',       desc: '2.5 high-volume, low latency' },
    { value: 'gemini-2.5-pro',        label: 'Gemini 2.5 Pro',        badge: 'PRECISION',  desc: 'Most capable 2.5 reasoning model' },
    // --- Generation 1.5 (Legacy) ---
    { value: 'gemini-1.5-flash',      label: 'Gemini 1.5 Flash',      badge: 'LEGACY',     desc: 'Stable legacy flash model' },
    { value: 'gemini-1.5-flash-8b',   label: 'Gemini 1.5 Flash-8B',   badge: 'MINI',       desc: 'Smallest & cheapest legacy option' },
    { value: 'gemini-1.5-pro',        label: 'Gemini 1.5 Pro',        badge: 'LEGACY-PRO', desc: 'Legacy high-capability model' },
  ];

  const [triggerForm, setTriggerForm] = useState({
    sku: 'SKU-404X',
    factory_code: 'FAC-12',
    delayed_days: 5,
    model_name: 'gemini-2.5-flash'
  });

  // Manual inputs for resuming gates
  const [overrideDamages, setOverrideDamages] = useState('');
  const [simulatedVendorReply, setSimulatedVendorReply] = useState('');
  const [autoRefresh, setAutoRefresh] = useState(true);

  // Fetch list of sessions
  const fetchSessions = async () => {
    try {
      const res = await fetch(`${API_BASE}/sessions`);
      if (res.ok) {
        const data = await res.json();
        setSessions(data);
        // Default select first session if none selected
        if (data.length > 0 && !selectedSessionId) {
          setSelectedSessionId(data[0].session_id);
        }
      }
    } catch (err) {
      console.error("Error fetching sessions:", err);
    }
  };

  // Fetch detailed info for selected session
  const fetchSessionDetails = async (id) => {
    if (!id) return;
    try {
      const res = await fetch(`${API_BASE}/sessions/${id}`);
      if (res.ok) {
        const data = await res.json();
        setCurrentSession(data);
        // Pre-fill fields
        if (data.state?.legal_analysis?.total_penalty) {
          setOverrideDamages(data.state.legal_analysis.total_penalty);
        }
      }
    } catch (err) {
      console.error("Error fetching session details:", err);
    }
  };

  useEffect(() => {
    fetchSessions();
  }, []);

  useEffect(() => {
    fetchSessionDetails(selectedSessionId);
  }, [selectedSessionId]);

  // Auto-refresh hook
  useEffect(() => {
    if (!autoRefresh || !selectedSessionId) return;
    const interval = setInterval(() => {
      fetchSessions();
      fetchSessionDetails(selectedSessionId);
    }, 3000);
    return () => clearInterval(interval);
  }, [autoRefresh, selectedSessionId]);

  // Trigger a new pipeline run
  const handleTrigger = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/sessions/trigger`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(triggerForm)
      });
      if (res.ok) {
        const data = await res.json();
        setSelectedSessionId(data.session_id);
        await fetchSessions();
      }
    } catch (err) {
      console.error("Error triggering session:", err);
    } finally {
      setLoading(false);
    }
  };

  // Resume a gate/interrupt
  const handleResume = async (interruptId, payload) => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/sessions/${selectedSessionId}/resume/${interruptId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      if (res.ok) {
        await fetchSessions();
        await fetchSessionDetails(selectedSessionId);
      }
    } catch (err) {
      console.error("Error resuming session:", err);
    } finally {
      setLoading(false);
    }
  };

  // Helper variables from current state
  const state = currentSession?.state || {};
  const activeInterrupt = currentSession?.active_interrupt;
  const isSuspended = currentSession?.is_suspended;

  // Determine current pipeline graph node states
  const getNodeClass = (nodeName) => {
    if (!currentSession) return 'pending';
    
    // Ingestion node
    if (nodeName === 'ingestion') {
      return state.sku ? 'completed' : 'active';
    }

    // Security screen node
    if (nodeName === 'security_screen') {
      if (state.security_alert) return 'escalated';
      if (state.factory_code && state.sku) return 'completed';
      return state.sku ? 'active' : 'pending';
    }
    
    // Legal review node
    if (nodeName === 'legal_sla') {
      if (state.security_alert) return 'pending';
      if (state.legal_analysis) return 'completed';
      return (state.factory_code && state.sku) ? 'active' : 'pending';
    }
    
    // Legal approval HITL gate
    if (nodeName === 'legal_approval') {
      if (state.security_alert) return 'pending';
      if (state.legal_approved !== undefined) return 'completed';
      if (activeInterrupt === 'legal_approval') return 'active';
      return 'pending';
    }
    
    // Sourcing search
    if (nodeName === 'sourcing') {
      if (state.security_alert) return 'pending';
      if (state.sourcing_analysis) return 'completed';
      if (state.legal_approved) return 'active';
      return 'pending';
    }
    
    // Sourcing premium check HITL gate
    if (nodeName === 'procurement') {
      if (state.security_alert) return 'pending';
      if (state.procurement_approved !== undefined) return 'completed';
      if (activeInterrupt === 'budget_approval') return 'active';
      if (state.sourcing_analysis) return 'active';
      return 'pending';
    }
    
    // Negotiation loop
    if (nodeName === 'negotiation') {
      if (state.security_alert) return 'pending';
      if (state.negotiation_resolved) return 'completed';
      if (state.negotiation_escalated) return 'escalated';
      if (activeInterrupt === 'vendor_reply') return 'active';
      if (state.procurement_approved) return 'active';
      return 'pending';
    }
    
    // PO signing
    if (nodeName === 'po_signing') {
      if (state.security_alert) return 'pending';
      if (state.po_signed) return 'completed';
      if (activeInterrupt === 'po_signature') return 'active';
      return 'pending';
    }

    return 'pending';
  };

  // FinOps metrics calculations
  const inputTokens = currentSession?.events ? currentSession.events.length * 1500 : 0;
  const outputTokens = currentSession?.events ? currentSession.events.length * 400 : 0;
  const tokenCost = ((inputTokens * 0.075 + outputTokens * 0.30) / 1000000).toFixed(4); // Gemini pricing mock
  const savings = state.legal_approved ? (state.approved_damages || 0.00) : 0.00;
  const standardPrice = state.standard_unit_price || 100.0;
  const premiumCost = state.final_sourcing_option ? ((state.final_sourcing_option.price - standardPrice) * 100) : 0.00;
  const netSaved = (savings - Math.max(0, premiumCost)).toFixed(2);

  return (
    <div className="app-container">
      {/* HEADER */}
      <header className="app-header">
        <div className="header-logo">
          <span className="logo-icon">⇄</span>
          <h1>SUPPLY CHAIN NEGO-BOT 2.0</h1>
        </div>
        <div className="header-controls">
          <label className="switch-container">
            <input 
              type="checkbox" 
              checked={autoRefresh} 
              onChange={(e) => setAutoRefresh(e.target.checked)} 
            />
            <span className="switch-label">Live Stream (3s)</span>
          </label>
          <span className={`status-badge ${loading ? 'loading' : 'idle'}`}>
            {loading ? 'SYNCING...' : 'API CONNECTED'}
          </span>
        </div>
      </header>

      {/* DASHBOARD LAYOUT */}
      <div className="dashboard-grid">
        
        {/* SIDEBAR - PIPELINE RUNS */}
        <aside className="sidebar">
          <div className="sidebar-section">
            <h3>Disruption Emulator</h3>
            <form onSubmit={handleTrigger} className="trigger-form">
              <div className="form-group">
                <label>SKU ID</label>
                <select 
                  value={triggerForm.sku} 
                  onChange={(e) => setTriggerForm({...triggerForm, sku: e.target.value})}
                >
                  <option value="SKU-404X">SKU-404X (Microchip Controller)</option>
                  <option value="SKU-777Z">SKU-777Z (Titanium Connector)</option>
                  <option value="SKU-100Y">SKU-100Y (Steel Housing - Buffer OK)</option>
                </select>
              </div>
              <div className="form-group">
                <label>Select AI Model
                  <span style={{ marginLeft: '0.5rem', fontSize: '0.65rem', color: 'var(--accent-cyan)', opacity: 0.7 }}>
                    (Free Tier)
                  </span>
                </label>
                <select
                  value={triggerForm.model_name}
                  onChange={(e) => setTriggerForm({...triggerForm, model_name: e.target.value})}
                >
                  {GEMINI_FREE_TIER_MODELS.map(m => (
                    <option key={m.value} value={m.value}>
                      {m.label} — {m.desc}
                    </option>
                  ))}
                </select>
                {/* Active model badge */}
                {(() => {
                  const active = GEMINI_FREE_TIER_MODELS.find(m => m.value === triggerForm.model_name);
                  return active ? (
                    <div style={{
                      display: 'flex', alignItems: 'center', gap: '0.4rem', marginTop: '0.3rem'
                    }}>
                      <span style={{
                        fontSize: '0.65rem', fontWeight: 700, padding: '0.1rem 0.4rem',
                        borderRadius: '4px', background: 'rgba(79,172,254,0.12)',
                        color: 'var(--accent-blue)', border: '1px solid rgba(79,172,254,0.25)',
                        letterSpacing: '0.05em'
                      }}>{active.badge}</span>
                      <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>{active.desc}</span>
                    </div>
                  ) : null;
                })()}
              </div>
              <div className="form-row">
                <div className="form-group">
                  <label>Factory</label>
                  <input 
                    type="text" 
                    value={triggerForm.factory_code} 
                    onChange={(e) => setTriggerForm({...triggerForm, factory_code: e.target.value})}
                  />
                </div>
                <div className="form-group">
                  <label>Delay (Days)</label>
                  <input 
                    type="number" 
                    min="1" 
                    value={triggerForm.delayed_days} 
                    onChange={(e) => setTriggerForm({...triggerForm, delayed_days: parseInt(e.target.value)})}
                  />
                </div>
              </div>
              <button type="submit" className="btn-trigger" disabled={loading}>
                {loading ? 'SCAFFOLDING...' : 'EMULATE WEBHOOK'}
              </button>
            </form>
          </div>

          <div className="sidebar-section list-section">
            <h3>Active Pipeline Runs</h3>
            {sessions.length === 0 ? (
              <p className="no-data">No active runs. Emulate a webhook disruption above to begin.</p>
            ) : (
              <div className="session-list">
                {sessions.map((s) => (
                  <div 
                    key={s.session_id} 
                    className={`session-card ${selectedSessionId === s.session_id ? 'active' : ''} ${s.is_suspended ? 'suspended' : ''}`}
                    onClick={() => setSelectedSessionId(s.session_id)}
                  >
                    <div className="session-card-header">
                      <span className="session-id">{s.session_id.substring(0, 8)}...</span>
                      <span className="session-time">{s.state?.sku ? (s.state.sku.length > 10 ? s.state.sku.substring(0, 10) + '...' : s.state.sku) : 'SKU UNKNOWN'}</span>
                    </div>
                    <div className="session-card-body">
                      <span>Status: {s.state?.security_alert ? '⚠️ QUARANTINED' : s.is_suspended ? '⏳ Suspended' : '✓ Finished'}</span>
                      {s.is_suspended && <span className="interrupt-tag">{s.active_interrupt}</span>}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </aside>

        {/* MAIN CONTROL CENTER PANEL */}
        <main className="main-content">
          
          {/* PIPELINE PROGRESS BAR */}
          <section className="pipeline-progress">
            <div className="section-title">
              <h2>Active Graph Execution Pathway</h2>
              {selectedSessionId && <span className="session-ref">Session: {selectedSessionId}</span>}
            </div>
            
            <div className="pipeline-graph">
              <div className={`graph-node ${getNodeClass('ingestion')}`}>
                <div className="node-icon">📥</div>
                <span>Webhook Ingest</span>
              </div>
              <div className="graph-arrow">➜</div>

              <div className={`graph-node ${getNodeClass('security_screen')}`}>
                <div className="node-icon">🛡️</div>
                <span>Security Shield</span>
              </div>
              <div className="graph-arrow">➜</div>
              
              <div className={`graph-node ${getNodeClass('legal_sla')}`}>
                <div className="node-icon">⚖</div>
                <span>SLA Damages Audit</span>
              </div>
              <div className="graph-arrow">➜</div>
              
              <div className={`graph-node ${getNodeClass('legal_approval')}`}>
                <div className="node-icon">👤</div>
                <span>Legal HITL Approval</span>
              </div>
              <div className="graph-arrow">➜</div>
              
              <div className={`graph-node ${getNodeClass('sourcing')}`}>
                <div className="node-icon">🔍</div>
                <span>Spot Catalog Sourcing</span>
              </div>
              <div className="graph-arrow">➜</div>
              
              <div className={`graph-node ${getNodeClass('procurement')}`}>
                <div className="node-icon">💳</div>
                <span>Premium Constraint Check</span>
              </div>
              <div className="graph-arrow">➜</div>
              
              <div className={`graph-node ${getNodeClass('negotiation')}`}>
                <div className="node-icon">✉</div>
                <span>Loop Negotiation</span>
              </div>
              <div className="graph-arrow">➜</div>
              
              <div className={`graph-node ${getNodeClass('po_signing')}`}>
                <div className="node-icon">✍</div>
                <span>PO Signoff</span>
              </div>
            </div>
          </section>

          {/* ACTIVE DETAILS & CONTROL PANELS */}
          {!currentSession ? (
            <div className="welcome-screen">
              <div className="welcome-icon">⇅</div>
              <h2>Supply-Chain SLA Breach & Spot Negotiator Dashboard</h2>
              <p>Select an active pipeline run from the sidebar, or trigger a new webhook simulation to watch the multi-agent graph execute.</p>
            </div>
          ) : (
            <div className="details-container">
              
              {/* ROW 1: SLA CONTRACT AUDITOR & SPOT SOURCING SCRAPER */}
              <div className="panels-row">
                
                {/* SLA CONTRACT AUDITOR */}
                <div className="glass-panel contract-panel">
                  <h3>SLA Contract Damage Auditor</h3>
                  
                  {state.legal_analysis ? (
                    <div className="data-box">
                      <div className="metadata-grid">
                        <div>
                          <strong>Supplier:</strong> {state.legal_analysis.supplier_name}
                        </div>
                        <div>
                          <strong>Penalty / Day:</strong> ${state.legal_analysis.liquidated_damages_per_day?.toLocaleString()}
                        </div>
                        <div>
                          <strong>Force Majeure:</strong> {state.legal_analysis.force_majeure_applies ? '⚠️ YES (Excluded)' : '✓ NO (Liable)'}
                        </div>
                        <div className="highlight">
                          <strong>Damages Owed:</strong> ${state.legal_analysis.total_penalty?.toLocaleString()}
                        </div>
                      </div>
                      
                      <div className="doc-segment">
                        <h4>Extracted Legal Clauses (Scrubbed / salted)</h4>
                        <p className="legal-text">
                          "...liquidated damages penalty of <span className="salt-tag">$5,000 per day</span> for delayed delivery of <span className="salt-tag">SKU-404X</span>... Force Majeure exclusions apply excluding labor strikes... Buyer target margin of <span className="salt-tag">[SALTED_TARGET_MARGIN]%</span>..."
                        </p>
                        <small className="audit-note">Note: PII & target financial metrics salted with random tokens to secure prompt nodes.</small>
                      </div>

                      {/* Gated approval button */}
                      {activeInterrupt === 'legal_approval' && (
                        <div className="hitl-actions">
                          <h4>Action Required: Legal Decision Override</h4>
                          <div className="action-row">
                            <input 
                              type="number" 
                              placeholder="Override Damages USD" 
                              value={overrideDamages} 
                              onChange={(e) => setOverrideDamages(e.target.value)}
                            />
                            <button 
                              className="btn-approve" 
                              onClick={() => handleResume('legal_approval', { approved: true, override_damages: parseFloat(overrideDamages) })}
                            >
                              Approve SLA Claim
                            </button>
                            <button 
                              className="btn-reject"
                              onClick={() => handleResume('legal_approval', { approved: false })}
                            >
                              Waive Claim
                            </button>
                          </div>
                        </div>
                      )}
                      
                      {state.legal_approved !== undefined && (
                        <div className="gate-resolution positive">
                          <span>✓ Legal Gate Resolved: <strong>{state.legal_approved ? 'APPROVED' : 'WAIVED'}</strong> (Claim value: ${state.approved_damages?.toLocaleString()})</span>
                        </div>
                      )}
                    </div>
                  ) : (
                    <p className="no-data-msg">
                      {state.security_alert 
                        ? "ALERT: Bypassed due to prompt injection security quarantine."
                        : "Waiting for legal auditor agent to parse contract SLA..."}
                    </p>
                  )}
                </div>

                {/* SPOT SOURCING SCRAPER */}
                <div className="glass-panel sourcing-panel">
                  <h3>B2B Scraped Supplier Catalog</h3>
                  
                  {state.sourcing_analysis ? (
                    <div className="data-box">
                      <div className="supplier-summary">
                        <div>
                          <strong>Best Spot Option:</strong> {state.sourcing_analysis.best_option?.vendor || 'None'}
                        </div>
                        <div>
                          <strong>Spot Price:</strong> {state.sourcing_analysis.best_option ? `$${state.sourcing_analysis.best_option.price?.toFixed(2)} / unit` : 'N/A'}
                        </div>
                        <div>
                          <strong>Standard Price:</strong> ${state.standard_unit_price?.toFixed(2)}
                        </div>
                        <div className={`premium-indicator ${state.sourcing_analysis.price_premium_percent > 10 ? 'violated' : 'safe'}`}>
                          <strong>Price Premium:</strong> {state.sourcing_analysis.price_premium_percent?.toFixed(1)}%
                        </div>
                      </div>

                      {state.sourcing_analysis.options?.length > 0 && (
                        <div className="supplier-grid-container">
                          <table className="supplier-grid">
                            <thead>
                              <tr>
                                <th>Supplier Name</th>
                                <th>Unit Price</th>
                                <th>Availability</th>
                                <th>Delivery Lead Time</th>
                              </tr>
                            </thead>
                            <tbody>
                              {state.sourcing_analysis.options.map((opt, i) => (
                                <tr key={i} className={state.sourcing_analysis.best_option?.vendor === opt.vendor ? 'best-row' : ''}>
                                  <td>{opt.vendor} {state.sourcing_analysis.best_option?.vendor === opt.vendor && '★'}</td>
                                  <td>${opt.price?.toFixed(2)}</td>
                                  <td>{opt.avail} units</td>
                                  <td>{opt.delivery_days} days</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      )}

                      {/* Gated approval button */}
                      {activeInterrupt === 'budget_approval' && (
                        <div className="hitl-actions">
                          <h4>Action Required: Finance Premium Override</h4>
                          <p className="action-warning">Sourcing premium is {state.sourcing_analysis.price_premium_percent?.toFixed(1)}% which exceeds the 10% company constraint. Slack alert dispatched.</p>
                          <div className="action-row">
                            <button 
                              className="btn-approve" 
                              onClick={() => handleResume('budget_approval', { approved: true })}
                            >
                              Approve Budget Override
                            </button>
                            <button 
                              className="btn-reject"
                              onClick={() => handleResume('budget_approval', { approved: false })}
                            >
                              Abort Sourcing Run
                            </button>
                          </div>
                        </div>
                      )}

                      {state.procurement_approved !== undefined && (
                        <div className="gate-resolution positive">
                          <span>✓ Procurement Gate Resolved: <strong>{state.procurement_approved ? 'BUDGET OVERRIDE APPROVED' : 'ABORTED'}</strong></span>
                        </div>
                      )}
                    </div>
                  ) : (
                    <p className="no-data-msg">
                      {state.security_alert
                        ? "ALERT: Bypassed due to prompt injection security quarantine."
                        : "Waiting for spot sourcing agent to compile catalogs..."}
                    </p>
                  )}
                </div>

              </div>

              {/* ROW 2: EMAIL NEGOTIATION THREAD & PO SIGNING */}
              <div className="panels-row">
                
                {/* NEGOTIATION THREAD LOGS */}
                <div className="glass-panel negotiation-panel">
                  <h3>Multi-Turn B2B Negotiation Terminal</h3>
                  
                  {state.negotiation_state ? (
                    <div className="data-box flex-column">
                      <div className="thread-meta">
                        <span>Turns Completed: {state.negotiation_turns || 0} / {MAX_NEGOTIATION_TURNS}</span>
                        <span className={`thread-status ${state.negotiation_resolved ? 'resolved' : state.negotiation_escalated ? 'escalated' : 'active'}`}>
                          {state.negotiation_resolved ? '✓ TERMS RESOLVED' : state.negotiation_escalated ? '⚠️ ESCALATED' : '⏳ ACTIVE'}
                        </span>
                      </div>

                      <div className="email-thread">
                        {state.negotiation_state.email_drafted && (
                          <div className="email-bubble agent-email">
                            <div className="email-header">
                              <strong>From:</strong> Procurement Agent Nego-Bot
                              <strong>To:</strong> {state.negotiation_state.vendor_email}
                            </div>
                            <div className="email-body-text">
                              {state.negotiation_state.email_drafted}
                            </div>
                          </div>
                        )}

                        {state.negotiation_thread?.map((msg, i) => (
                          <div key={i} className={`email-bubble ${msg.sender.includes('Agent') ? 'agent-email' : 'vendor-email'}`}>
                            <div className="email-header">
                              <strong>From:</strong> {msg.sender}
                            </div>
                            <div className="email-body-text">{msg.message}</div>
                          </div>
                        ))}
                      </div>

                      {/* Gated approval button */}
                      {activeInterrupt === 'vendor_reply' && (
                        <div className="hitl-actions">
                          <h4>Emulate Incoming Vendor Email Response</h4>
                          <div className="email-emulate-row">
                            <textarea 
                              rows="3"
                              placeholder="Type incoming vendor email reply... (keywords like 'agree', 'accept' will auto-resolve the negotiation)" 
                              value={simulatedVendorReply} 
                              onChange={(e) => setSimulatedVendorReply(e.target.value)}
                            />
                            <button 
                              className="btn-trigger" 
                              onClick={() => {
                                handleResume('vendor_reply', { reply_body: simulatedVendorReply });
                                setSimulatedVendorReply('');
                              }}
                            >
                              Send Simulated Reply
                            </button>
                          </div>
                        </div>
                      )}

                      {state.negotiation_resolved && (
                        <div className="gate-resolution positive">
                          <span>✓ Negotiation Settled: Agreed Unit Price is <strong>${state.negotiation_final_price?.toFixed(2)}</strong></span>
                        </div>
                      )}

                      {state.negotiation_escalated && (
                        <div className="gate-resolution negative">
                          <span>⚠️ Negotiation Escalated to Human Buyer Ticket: <strong>{state.ticket_id}</strong> (Turns exceeded limit)</span>
                        </div>
                      )}
                    </div>
                  ) : (
                    <p className="no-data-msg">
                      {state.security_alert
                        ? "ALERT: Bypassed due to prompt injection security quarantine."
                        : "Waiting for negotiation agent to initiate proposal..."}
                    </p>
                  )}
                </div>

                {/* PURCHASE ORDER SIGNING */}
                <div className="glass-panel po-panel">
                  <h3>PO Signing Validation Layer</h3>
                  
                  {state.negotiation_resolved ? (
                    <div className="data-box">
                      <div className="po-details">
                        <h4>Immutable PO Manifest Buffer</h4>
                        <div className="po-manifest">
                          <div><strong>PO Identifier:</strong> PO-{state.sku}-AUTO</div>
                          <div><strong>Item SKU:</strong> {state.sku}</div>
                          <div><strong>Order Qty:</strong> 100 units</div>
                          <div><strong>Agreed Unit Price:</strong> ${state.negotiation_final_price?.toFixed(2)}</div>
                          <div className="po-total"><strong>PO Total Amount:</strong> ${(100 * state.negotiation_final_price).toLocaleString('en-US', { style: 'currency', currency: 'USD' })}</div>
                        </div>
                      </div>

                      {/* Gated approval button */}
                      {activeInterrupt === 'po_signature' && (
                        <div className="hitl-actions">
                          <h4>Action Required: Operations Director PO Signature</h4>
                          <div className="action-row">
                            <button 
                              className="btn-approve signature-btn" 
                              onClick={() => handleResume('po_signature', { signed: true })}
                            >
                              Apply Digital Signature (Sign PO)
                            </button>
                            <button 
                              className="btn-reject"
                              onClick={() => handleResume('po_signature', { signed: false })}
                            >
                              Reject PO
                            </button>
                          </div>
                        </div>
                      )}

                      {state.po_signed && (
                        <div className="gate-resolution positive">
                          <span>✓ PO Signed and Committed to ERP Database: <strong>{state.po_database_result}</strong></span>
                        </div>
                      )}
                    </div>
                  ) : (
                    <p className="no-data-msg">
                      {state.security_alert
                        ? "ALERT: Bypassed due to prompt injection security quarantine."
                        : "Waiting for negotiation closure to generate Purchase Order manifest..."}
                    </p>
                  )}
                </div>

              </div>

              {/* PIPELINE AUDIT TRAIL / REAL-TIME EVENT LOGS FEED */}
              {currentSession && currentSession.events && (
                <section className="audit-log-section">
                  <h3>Pipeline Execution Audit Log</h3>
                  <div className="terminal-window">
                    <div className="terminal-header">
                      <div className="terminal-buttons">
                        <span className="term-btn close"></span>
                        <span className="term-btn minimize"></span>
                        <span className="term-btn expand"></span>
                      </div>
                      <span className="terminal-title">operator@nego-bot-orchestrator: ~events</span>
                    </div>
                    <div className="terminal-body">
                      {currentSession.events.length === 0 ? (
                        <div className="terminal-line text-muted">No events recorded for this session.</div>
                      ) : (
                        currentSession.events.map((evt, idx) => {
                          const timestamp = evt.timestamp 
                            ? new Date(evt.timestamp * 1000).toLocaleTimeString() 
                            : new Date().toLocaleTimeString();
                          
                          // Node name extractor
                          let nodeName = 'system';
                          if (evt.node_info?.path) {
                            const parts = evt.node_info.path.split('/');
                            const lastPart = parts[parts.length - 1];
                            nodeName = lastPart.split('@')[0];
                          } else if (evt.author) {
                            nodeName = evt.author;
                          }

                          // Check for specific payloads
                          const stateDelta = evt.actions?.state_delta;
                          const hasStateDelta = stateDelta && Object.keys(stateDelta).length > 0;
                          
                          const route = evt.actions?.route;
                          
                          // Extract tool calls / text parts
                          const parts = evt.content?.parts || [];
                          const toolCalls = parts.filter(p => p.function_call).map(p => p.function_call);
                          const toolResponses = parts.filter(p => p.function_response).map(p => p.function_response);
                          const textParts = parts.filter(p => p.text && p.text.trim()).map(p => p.text.trim());

                          // Node color class
                          let nodeColorClass = 'text-gray';
                          if (nodeName.toLowerCase().includes('legal')) nodeColorClass = 'text-cyan';
                          else if (nodeName.toLowerCase().includes('sourcing')) nodeColorClass = 'text-blue';
                          else if (nodeName.toLowerCase().includes('procurement')) nodeColorClass = 'text-yellow';
                          else if (nodeName.toLowerCase().includes('negotiation')) nodeColorClass = 'text-orange';
                          else if (nodeName.toLowerCase().includes('signing')) nodeColorClass = 'text-green';
                          else if (nodeName.toLowerCase().includes('disruption') || nodeName.toLowerCase().includes('ingest')) nodeColorClass = 'text-magenta';
                          else if (nodeName.toLowerCase().includes('security')) nodeColorClass = 'text-cyan';

                          return (
                            <div key={evt.id || idx} className="terminal-event">
                              <div className="terminal-line header-line">
                                <span className="timestamp">[{timestamp}]</span>{' '}
                                <span className={`node-badge ${nodeColorClass}`}>&lt;{nodeName}&gt;</span>{' '}
                                <span className="event-type">({evt.event_type || 'Event'})</span>
                              </div>

                              {/* LLM Text Outputs */}
                              {textParts.map((txt, tIdx) => (
                                <div key={tIdx} className="terminal-line indent text-body">
                                  <span className="prefix">└─ LLM:</span> {txt}
                                </div>
                              ))}

                              {/* Tool Calls */}
                              {toolCalls.map((tc, tcIdx) => (
                                <div key={tcIdx} className="terminal-line indent tool-call">
                                  <span className="prefix">└─ TOOL CALL:</span>{' '}
                                  <span className="tool-name">{tc.name}</span>
                                  <pre className="tool-args">{JSON.stringify(tc.args, null, 2)}</pre>
                                </div>
                              ))}

                              {/* Tool Responses */}
                              {toolResponses.map((tr, trIdx) => (
                                <div key={trIdx} className="terminal-line indent tool-response">
                                  <span className="prefix">└─ TOOL RETURN [{tr.name}]:</span>{' '}
                                  <pre className="tool-val">{JSON.stringify(tr.response, null, 2)}</pre>
                                </div>
                              ))}

                              {/* State Delta */}
                              {hasStateDelta && (
                                <div className="terminal-line indent state-delta">
                                  <span className="prefix">└─ STATE UPDATED:</span>
                                  <pre className="delta-val">{JSON.stringify(stateDelta, null, 2)}</pre>
                                </div>
                              )}

                              {/* Branch Route */}
                              {route && (
                                <div className="terminal-line indent route-taken">
                                  <span className="prefix">└─ BRANCH ROUTE:</span>{' '}
                                  <span className="route-tag">➔ {route}</span>
                                </div>
                              )}
                            </div>
                          );
                        })
                      )}
                    </div>
                  </div>
                </section>
              )}

              {/* FINOPS STATS & LATENCY DASHBOARD */}
              <section className="finops-dashboard">
                <h3>Financial Operations & AI Token Telemetry Dashboard</h3>
                <div className="finops-grid">
                  <div className="metric-card">
                    <span className="metric-label">Active AI Model</span>
                    <span className="metric-value" style={{ fontSize: '0.9rem', textTransform: 'none', wordBreak: 'break-all', letterSpacing: 0 }}>
                      {state.selected_model || triggerForm.model_name || 'gemini-2.5-flash'}
                    </span>
                    {(() => {
                      const modelId = state.selected_model || triggerForm.model_name || 'gemini-2.5-flash';
                      const m = GEMINI_FREE_TIER_MODELS.find(x => x.value === modelId);
                      return m ? (
                        <span className="metric-sub" style={{ display: 'flex', gap: '0.3rem', alignItems: 'center', flexWrap: 'wrap' }}>
                          <span style={{
                            fontSize: '0.62rem', fontWeight: 700, padding: '0.1rem 0.35rem',
                            borderRadius: '4px', background: 'rgba(0,242,254,0.08)',
                            color: 'var(--accent-cyan)', border: '1px solid rgba(0,242,254,0.2)'
                          }}>{m.badge}</span>
                          <span style={{ color: 'var(--text-muted)', fontSize: '0.68rem' }}>{m.desc}</span>
                        </span>
                      ) : <span className="metric-sub text-gray">Free Tier Model</span>;
                    })()}
                  </div>

                  <div className="metric-card">
                    <span className="metric-label">Estimated Token Consumption</span>
                    <span className="metric-value">{(inputTokens + outputTokens).toLocaleString()} tokens</span>
                    <span className="metric-sub text-gray">In: {inputTokens.toLocaleString()} | Out: {outputTokens.toLocaleString()}</span>
                  </div>
                  
                  <div className="metric-card">
                    <span className="metric-label">Model Invocation Cost (USD)</span>
                    <span className="metric-value">${tokenCost}</span>
                    <span className="metric-sub text-green">Telemetry: otel_to_cloud=False</span>
                  </div>
                  
                  <div className="metric-card">
                    <span className="metric-label">Contract Liability Recovered</span>
                    <span className="metric-value">${savings.toLocaleString()}</span>
                    <span className="metric-sub text-green">{state.legal_approved ? 'Audited & Claimed' : 'None'}</span>
                  </div>
                  
                  <div className="metric-card">
                    <span className="metric-label">Net Value Recovered</span>
                    <span className={`metric-value ${parseFloat(netSaved) >= 0 ? 'text-green' : 'text-red'}`}>
                      ${parseFloat(netSaved).toLocaleString()}
                    </span>
                    <span className="metric-sub text-gray">Spot premium overhead: ${Math.max(0, premiumCost).toLocaleString()}</span>
                  </div>
                </div>
              </section>

            </div>
          )}

        </main>
      </div>
    </div>
  );
}
