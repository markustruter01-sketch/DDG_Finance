export function GlassOrb() {
  const glass = {
    panel: {
      background: "rgba(255,255,255,0.06)",
      backdropFilter: "blur(24px) saturate(180%)",
      WebkitBackdropFilter: "blur(24px) saturate(180%)",
      border: "1px solid rgba(255,255,255,0.13)",
      boxShadow: "0 8px 32px rgba(0,0,0,0.4), inset 0 1px 0 rgba(255,255,255,0.08)",
    } as React.CSSProperties,
    pillActive: {
      background: "rgba(139,92,246,0.25)",
      backdropFilter: "blur(12px)",
      WebkitBackdropFilter: "blur(12px)",
      border: "1px solid rgba(139,92,246,0.45)",
      boxShadow: "0 0 18px rgba(139,92,246,0.25), inset 0 1px 0 rgba(255,255,255,0.12)",
    } as React.CSSProperties,
    pill: {
      background: "rgba(255,255,255,0.04)",
      backdropFilter: "blur(12px)",
      WebkitBackdropFilter: "blur(12px)",
      border: "1px solid rgba(255,255,255,0.08)",
    } as React.CSSProperties,
    navBtn: (active: boolean, color: string) => ({
      background: active ? `${color}22` : "rgba(10,14,30,0.65)",
      backdropFilter: "blur(20px) saturate(200%)",
      WebkitBackdropFilter: "blur(20px) saturate(200%)",
      border: `1px solid ${active ? color + "55" : "rgba(255,255,255,0.08)"}`,
      boxShadow: active
        ? `0 4px 24px ${color}33, inset 0 1px 0 ${color}22`
        : "0 4px 20px rgba(0,0,0,0.5), inset 0 1px 0 rgba(255,255,255,0.04)",
    }) as React.CSSProperties,
    card: {
      background: "rgba(255,255,255,0.04)",
      backdropFilter: "blur(16px)",
      WebkitBackdropFilter: "blur(16px)",
      border: "1px solid rgba(255,255,255,0.09)",
      borderRadius: 10,
    } as React.CSSProperties,
  };

  const mono = "font-['SF_Mono','JetBrains_Mono',monospace]";
  const label = "text-[9px] tracking-[0.15em] uppercase text-white/35";
  const headerVal = "text-[13px] font-bold text-white/90";

  const closedTrades = [
    { sym: "CHF-X",    side:"L", val:"$7,887",       pnl:"+$101", win:true },
    { sym: "EURGBP-X", side:"L", val:"$7,387",        pnl:"$31",   win:false },
    { sym: "AUDUSD-X", side:"L", val:"$9,983",        pnl:"+$12",  win:true },
    { sym: "GBPJPY-X", side:"L", val:"$1,583,233",    pnl:"+$41",  win:true },
    { sym: "EUR3JPY-X",side:"L", val:"$1,583,284",    pnl:"$10",   win:false },
    { sym: "GBPUSD-X", side:"L", val:"$18,001",       pnl:"+$49",  win:true },
    { sym: "EURUSD-X", side:"L", val:"$9,984",        pnl:"$53",   win:false },
    { sym: "JPY-X",    side:"L", val:"$1,592,720",    pnl:"$42",   win:false },
    { sym: "CAD-X",    side:"L", val:"$13,710",       pnl:"$52",   win:false },
    { sym: "CAD-X",    side:"L", val:"$13,665",       pnl:"$51",   win:false },
  ];

  const openPositions = [
    { sym:"AMD",  side:"L", val:"$13,656", pnl:"+$1.1k" },
    { sym:"MS",   side:"L", val:"$13,629", pnl:"+$911" },
    { sym:"INTC", side:"L", val:"$11,113", pnl:"+$593" },
    { sym:"MUE",  side:"L", val:"$14,046", pnl:"+$453" },
    { sym:"ELV",  side:"L", val:"$13,393", pnl:"+$387" },
    { sym:"UNH",  side:"L", val:"$26,997", pnl:"+$237" },
    { sym:"TXN",  side:"L", val:"$13,858", pnl:"+$149" },
  ];

  const bots = [
    { short:"Oracle",  color:"#a78bfa", pnl:"-$8.1k",  active:true  },
    { short:"SPY/QQQ", color:"#fbbf24", pnl:"+$11.4k", active:true  },
    { short:"Jerome",  color:"#f87171", pnl:"+$0",     active:true  },
    { short:"Forex",   color:"#60a5fa", pnl:"-$201",   active:false },
    { short:"Listing", color:"#fb923c", pnl:"+$6",     active:true  },
    { short:"Event",   color:"#8b5cf6", pnl:"+$0",     active:true  },
    { short:"Depeg",   color:"#fb7185", pnl:"+$0",     active:true  },
    { short:"Meme",    color:"#a3e635", pnl:"+$0",     active:true  },
  ];

  const tabs = ["LIVE","MATH","BOTS","HEALTH","LEARNING","ORB","PERFORMANCE","ARCHITECTURE"];

  return (
    <div
      style={{
        width: "100%", height: "100vh", overflow: "hidden",
        background: "radial-gradient(ellipse at 55% 45%, #0d1829 0%, #050810 55%, #000000 100%)",
        fontFamily: "'Inter','SF Pro Display',-apple-system,sans-serif",
        display: "flex", flexDirection: "column", position: "relative",
      }}
    >
      {/* ── STAR FIELD ── */}
      <div style={{ position:"absolute", inset:0, pointerEvents:"none", overflow:"hidden", zIndex:0 }}>
        {Array.from({length:60}).map((_,i)=>(
          <div key={i} style={{
            position:"absolute",
            left:`${(i*37.3)%100}%`, top:`${(i*53.7)%100}%`,
            width: i%7===0?2:1, height: i%7===0?2:1,
            borderRadius:"50%",
            background:`rgba(255,255,255,${0.15+((i*13)%3)*0.15})`,
          }}/>
        ))}
      </div>

      {/* ── STREAM HEADER BAR ── */}
      <div style={{
        ...glass.panel,
        borderRadius: 0,
        borderLeft: "none", borderRight: "none", borderTop: "none",
        padding: "0 16px",
        display: "flex", alignItems: "center", gap: 0,
        height: 36, flexShrink: 0, zIndex: 10,
        background: "rgba(8,12,24,0.72)",
      }}>
        {/* LIVE badge */}
        <div style={{
          display:"flex", alignItems:"center", gap:5,
          background:"rgba(34,197,94,0.15)", border:"1px solid rgba(34,197,94,0.3)",
          borderRadius:6, padding:"2px 8px", marginRight:16,
          backdropFilter:"blur(8px)",
        }}>
          <div style={{width:5,height:5,borderRadius:"50%",background:"#4ade80",boxShadow:"0 0 6px #4ade80"}}/>
          <span style={{color:"#4ade80",fontSize:9,fontWeight:800,letterSpacing:"0.12em"}}>LIVE</span>
        </div>
        {[
          {l:"Total P&L",v:"+$3,139",s:"+0.4%",c:"#4ade80"},
          {l:"Vault",v:"$546",s:"secured",c:"#fbbf24"},
          {l:"Best Trade",v:"+$268",s:"HPE",c:"#4ade80"},
          {l:"Worst Trade",v:"-$75",s:"USO",c:"#f87171"},
          {l:"Win Rate",v:"64%",s:"175W/99L",c:"#e2e8f0"},
          {l:"Trades",v:"175W",s:"/ 99L",c:"#e2e8f0"},
          {l:"Math Audit",v:"—",s:"0 checks",c:"#94a3b8"},
          {l:"Platform Equity",v:"$803,139",s:"+0.4%",c:"#4ade80"},
          {l:"Active Bots",v:"1/4",s:"",c:"#22d3ee"},
        ].map((m,i)=>(
          <div key={i} style={{
            display:"flex",flexDirection:"column",justifyContent:"center",
            padding:"0 14px",
            borderLeft:"1px solid rgba(255,255,255,0.06)",
            height:"100%",
          }}>
            <span style={{color:"rgba(148,163,184,0.5)",fontSize:8,fontWeight:600,letterSpacing:"0.1em",textTransform:"uppercase"}}>{m.l}</span>
            <div style={{display:"flex",alignItems:"baseline",gap:4}}>
              <span style={{color:m.c,fontSize:11,fontWeight:700,fontFamily:"monospace"}}>{m.v}</span>
              {m.s&&<span style={{color:"rgba(148,163,184,0.45)",fontSize:9,fontFamily:"monospace"}}>{m.s}</span>}
            </div>
          </div>
        ))}
        <span style={{marginLeft:"auto",color:"rgba(148,163,184,0.5)",fontSize:10,fontFamily:"monospace"}}>15:11:32</span>
      </div>

      {/* ── SUB-NAV ── */}
      <div style={{
        ...glass.panel,
        borderRadius:0, borderLeft:"none", borderRight:"none",
        background:"rgba(6,9,20,0.6)",
        padding:"0 16px",
        display:"flex", alignItems:"center", gap:3,
        height:42, flexShrink:0, zIndex:10,
      }}>
        {tabs.map(t=>{
          const active = t==="ORB";
          return (
            <div key={t} style={{
              ...(active ? glass.pillActive : glass.pill),
              padding:"5px 14px",
              borderRadius:8,
              cursor:"pointer",
            }}>
              <span style={{
                color: active ? "#a78bfa" : "rgba(255,255,255,0.65)",
                fontSize:11, fontWeight:700, letterSpacing:"0.06em",
              }}>{t}</span>
            </div>
          );
        })}
        <div style={{marginLeft:"auto",display:"flex",alignItems:"center",gap:8}}>
          <span style={{color:"rgba(148,163,184,0.4)",fontSize:9,fontWeight:600,letterSpacing:"0.1em",textTransform:"uppercase"}}>Interval</span>
          <div style={{...glass.card,padding:"2px 10px",background:"rgba(255,255,255,0.07)"}}>
            <span style={{color:"#e2e8f0",fontSize:10,fontFamily:"monospace",fontWeight:700}}>25</span>
          </div>
          <span style={{color:"rgba(148,163,184,0.4)",fontSize:9}}>s</span>
          <div style={{
            ...glass.panel, borderRadius:8, padding:"4px 12px",
            background:"rgba(34,197,94,0.12)",
            border:"1px solid rgba(34,197,94,0.3)",
            boxShadow:"0 0 14px rgba(34,197,94,0.15), inset 0 1px 0 rgba(34,197,94,0.12)",
          }}>
            <span style={{color:"#4ade80",fontSize:9,fontWeight:800,letterSpacing:"0.1em"}}>◉ AUTO-CYCLE</span>
          </div>
        </div>
      </div>

      {/* ── MAIN CONTENT ── */}
      <div style={{flex:1,display:"flex",position:"relative",overflow:"hidden",zIndex:1}}>

        {/* ── LEFT PANEL: CLOSED TRADES ── */}
        <div style={{
          ...glass.panel,
          width:240, margin:"12px 0 12px 12px",
          borderRadius:16, display:"flex", flexDirection:"column", overflow:"hidden",
          flexShrink:0,
        }}>
          <div style={{
            padding:"10px 14px 8px",
            borderBottom:"1px solid rgba(255,255,255,0.07)",
          }}>
            <span style={{
              color:"rgba(255,255,255,0.55)", fontSize:9, fontWeight:700,
              letterSpacing:"0.18em", textTransform:"uppercase",
            }}>◂ Closed Trades</span>
          </div>
          <div style={{overflowY:"auto",flex:1}}>
            {closedTrades.map((t,i)=>(
              <div key={i} style={{
                display:"flex", alignItems:"center", justifyContent:"space-between",
                padding:"7px 14px",
                borderBottom:"1px solid rgba(255,255,255,0.04)",
              }}>
                <div style={{display:"flex",alignItems:"center",gap:7}}>
                  <div style={{
                    width:5,height:5,borderRadius:"50%",
                    background: t.win?"#4ade80":"rgba(148,163,184,0.3)",
                    boxShadow: t.win?"0 0 5px #4ade8066":"none",
                    flexShrink:0,
                  }}/>
                  <div>
                    <div style={{display:"flex",gap:5,alignItems:"center"}}>
                      <span style={{color:"rgba(255,255,255,0.85)",fontSize:10,fontWeight:600}}>{t.sym}</span>
                      <span style={{
                        background:"rgba(99,102,241,0.2)",
                        border:"1px solid rgba(99,102,241,0.3)",
                        borderRadius:3,padding:"0 4px",
                        color:"#818cf8",fontSize:8,fontWeight:700,
                      }}>{t.side}</span>
                    </div>
                    <div style={{color:"rgba(148,163,184,0.5)",fontSize:8,fontFamily:"monospace"}}>{t.val}</div>
                  </div>
                </div>
                <div style={{display:"flex",alignItems:"center",gap:5}}>
                  <span style={{
                    color: t.win?"#4ade80":"rgba(148,163,184,0.5)",
                    fontSize:10, fontWeight:700, fontFamily:"monospace",
                  }}>{t.pnl}</span>
                  <span style={{color: t.win?"#4ade80":"#f87171",fontSize:9}}>{t.win?"✓":"✗"}</span>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* ── CENTER: BLACK HOLE + WIDGETS ── */}
        <div style={{flex:1,position:"relative",display:"flex",alignItems:"center",justifyContent:"center"}}>

          {/* Digital Dynamics Badge */}
          <div style={{
            position:"absolute", top:16, left:"50%", transform:"translateX(-50%)",
            ...glass.panel, borderRadius:20,
            padding:"5px 14px",
            display:"flex", alignItems:"center", gap:7,
            zIndex:5,
          }}>
            <span style={{fontSize:8,color:"rgba(255,255,255,0.35)",letterSpacing:"0.1em",textTransform:"uppercase"}}>⚡ Powered by</span>
            <span style={{fontSize:9,fontWeight:800,color:"rgba(255,255,255,0.8)",letterSpacing:"0.06em"}}>DIGITAL DYNAMICS GROUP</span>
            <span style={{fontSize:11}}>☁</span>
          </div>

          {/* TRADING ENGINE title */}
          <div style={{position:"absolute",top:48,left:"50%",transform:"translateX(-50%)",textAlign:"center",zIndex:5}}>
            <div style={{display:"flex",alignItems:"center",gap:12,justifyContent:"center"}}>
              <span style={{color:"rgba(251,146,60,0.7)",fontSize:12}}>◈</span>
              <span style={{
                fontSize:28, fontWeight:900,
                letterSpacing:"0.25em",
                background:"linear-gradient(135deg,#fb923c 0%,#fbbf24 50%,#fb923c 100%)",
                WebkitBackgroundClip:"text", WebkitTextFillColor:"transparent",
                textShadow:"none",
              }}>TRADING ENGINE</span>
              <span style={{color:"rgba(251,146,60,0.7)",fontSize:12}}>◈</span>
            </div>
            <div style={{color:"rgba(148,163,184,0.4)",fontSize:9,letterSpacing:"0.22em",marginTop:2}}>LIVE MARKET CONSCIOUSNESS</div>
          </div>

          {/* Black Hole ORB */}
          <div style={{
            width:360, height:360,
            borderRadius:"50%",
            background:"radial-gradient(circle at 35% 40%, #2a1500 0%, #0d0900 40%, #000000 70%)",
            boxShadow:[
              "0 0 80px 20px rgba(251,146,60,0.12)",
              "0 0 160px 60px rgba(251,146,60,0.06)",
              "inset 0 0 60px rgba(0,0,0,0.9)",
            ].join(","),
            position:"relative",
            overflow:"hidden",
          }}>
            {/* Accretion disk glow */}
            <div style={{
              position:"absolute",top:"35%",left:"-20%",
              width:"140%",height:"30%",
              background:"linear-gradient(90deg,transparent 0%,rgba(251,146,60,0.35) 20%,rgba(251,200,60,0.55) 45%,rgba(251,146,60,0.35) 70%,transparent 100%)",
              borderRadius:"50%",
              transform:"rotate(-8deg)",
              filter:"blur(8px)",
            }}/>
            {/* Inner void */}
            <div style={{
              position:"absolute",top:"22%",left:"22%",
              width:"56%",height:"56%",
              borderRadius:"50%",
              background:"#000000",
              boxShadow:"0 0 30px 15px #000000",
            }}/>
            {/* Photon ring */}
            <div style={{
              position:"absolute",top:"18%",left:"18%",
              width:"64%",height:"64%",
              borderRadius:"50%",
              border:"2px solid rgba(251,180,60,0.3)",
              boxShadow:"0 0 20px rgba(251,180,60,0.2), inset 0 0 20px rgba(251,180,60,0.1)",
            }}/>
          </div>

          {/* Signal confidence bubble */}
          <div style={{
            position:"absolute", top:"52%", left:"56%",
            ...glass.panel, borderRadius:12,
            padding:"5px 12px",
            zIndex:5,
          }}>
            <span style={{color:"#22d3ee",fontSize:10,fontWeight:700,fontFamily:"monospace"}}>signal confidence: 74%</span>
          </div>

          {/* ── SYNAPTIC MATH WIDGET (bottom-left) ── */}
          <div style={{
            position:"absolute", bottom:12, left:12,
            ...glass.panel, borderRadius:14,
            padding:"10px 14px",
            maxWidth:"calc(50vw - 80px)",
          }}>
            <div style={{color:"rgba(255,255,255,0.35)",fontSize:8,letterSpacing:"0.16em",textTransform:"uppercase",marginBottom:8}}>
              ◂ Synaptic Math Audit Engine v4.1
            </div>
            <div style={{display:"flex",gap:8}}>
              {[
                {label:"SHARPE",eq:"S=(Rp-Rf)/σp",val:"1.63",c:"#22d3ee"},
                {label:"KELLY", eq:"f*=(bp-q)/b",  val:"13.8%",c:"#22d3ee"},
                {label:"VaR",   eq:"VaR=μ-zσ√t",  val:"$4,820",c:"#22d3ee", active:true},
                {label:"SORTINO",eq:"S=(Rp-MAR)/σd",val:"2.12",c:"#22d3ee"},
              ].map((f,i)=>(
                <div key={i} style={{
                  background: f.active ? "rgba(34,211,238,0.06)" : "rgba(0,0,0,0.3)",
                  border:`1px solid ${f.active?"rgba(34,211,238,0.45)":"rgba(34,211,238,0.12)"}`,
                  borderRadius:9,
                  padding:"8px 12px",
                  minWidth:110,
                  backdropFilter:"blur(8px)",
                  boxShadow: f.active ? "0 0 20px rgba(34,211,238,0.2), inset 0 1px 0 rgba(34,211,238,0.1)" : "none",
                }}>
                  <div style={{color:f.c,fontSize:8,fontWeight:700,letterSpacing:"0.12em",textTransform:"uppercase",marginBottom:4}}>{f.label}</div>
                  <div style={{color:"rgba(226,232,240,0.85)",fontSize:12,fontFamily:"monospace",fontWeight:600,marginBottom:3}}>{f.eq}</div>
                  <div style={{color:f.c,fontSize:13,fontFamily:"monospace",fontWeight:800}}>{f.val}</div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* ── RIGHT PANEL: OPEN POSITIONS ── */}
        <div style={{
          ...glass.panel,
          width:240, margin:"12px 12px 12px 0",
          borderRadius:16, display:"flex", flexDirection:"column", overflow:"hidden",
          flexShrink:0,
        }}>
          <div style={{
            padding:"10px 14px 8px",
            borderBottom:"1px solid rgba(255,255,255,0.07)",
            display:"flex",justifyContent:"space-between",alignItems:"center",
          }}>
            <span style={{color:"rgba(255,255,255,0.55)",fontSize:9,fontWeight:700,letterSpacing:"0.18em",textTransform:"uppercase"}}>Open Positions ◂</span>
          </div>
          <div style={{overflowY:"auto",flex:1}}>
            {openPositions.map((p,i)=>(
              <div key={i} style={{
                display:"flex",alignItems:"center",justifyContent:"space-between",
                padding:"8px 14px",
                borderBottom:"1px solid rgba(255,255,255,0.04)",
              }}>
                <div style={{display:"flex",alignItems:"center",gap:8}}>
                  <div style={{
                    width:18,height:18,borderRadius:"50%",
                    background:"rgba(34,211,238,0.1)",
                    border:"1px solid rgba(34,211,238,0.2)",
                    display:"flex",alignItems:"center",justifyContent:"center",
                    fontSize:6,color:"#22d3ee",fontWeight:800,
                  }}>◈</div>
                  <div>
                    <div style={{display:"flex",gap:5,alignItems:"center"}}>
                      <span style={{color:"rgba(255,255,255,0.85)",fontSize:10,fontWeight:600}}>{p.sym}</span>
                      <span style={{
                        background:"rgba(99,102,241,0.2)",border:"1px solid rgba(99,102,241,0.3)",
                        borderRadius:3,padding:"0 4px",color:"#818cf8",fontSize:8,fontWeight:700,
                      }}>{p.side}</span>
                    </div>
                    <div style={{color:"rgba(148,163,184,0.5)",fontSize:8,fontFamily:"monospace"}}>{p.val}</div>
                  </div>
                </div>
                <span style={{color:"#4ade80",fontSize:11,fontWeight:700,fontFamily:"monospace"}}>{p.pnl}</span>
              </div>
            ))}
          </div>

          {/* Bot Grid Status */}
          <div style={{
            borderTop:"1px solid rgba(255,255,255,0.07)",
            padding:"10px 12px",
          }}>
            <div style={{color:"rgba(255,255,255,0.35)",fontSize:8,letterSpacing:"0.14em",textTransform:"uppercase",marginBottom:8}}>◂ Bot Grid Status</div>
            <div style={{display:"grid",gridTemplateColumns:"repeat(4,1fr)",gridTemplateRows:"repeat(2,auto)",gap:4}}>
              {bots.map((b,i)=>(
                <div key={i} style={{
                  background: b.active?"rgba(255,255,255,0.04)":"rgba(0,0,0,0.2)",
                  border:`1px solid ${b.active?b.color+"30":"rgba(100,116,139,0.15)"}`,
                  borderRadius:7,
                  padding:"5px 6px",
                  backdropFilter:"blur(8px)",
                }}>
                  <div style={{display:"flex",alignItems:"center",gap:3,marginBottom:3}}>
                    <div style={{
                      width:4,height:4,borderRadius:"50%",
                      background:b.active?"#4ade80":"#f87171",
                      boxShadow:b.active?"0 0 5px #4ade8088":"none",
                    }}/>
                    <span style={{color:b.color,fontSize:6,fontWeight:800,letterSpacing:"0.06em",textTransform:"uppercase",lineHeight:1}}>{b.short}</span>
                  </div>
                  <div style={{color:b.pnl.startsWith("+")?"#4ade80":b.pnl==="+$0"?"#94a3b8":"#f87171",fontSize:8,fontFamily:"monospace",fontWeight:700}}>{b.pnl}</div>
                  <div style={{color:b.active?"rgba(74,222,128,0.5)":"rgba(248,113,113,0.5)",fontSize:5,textTransform:"uppercase",letterSpacing:"0.1em",marginTop:1}}>{b.active?"active":"paused"}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* ── GLOBAL NAV ── */}
      <div style={{
        position:"absolute", bottom:16, left:"50%", transform:"translateX(-50%)",
        display:"flex", gap:10, zIndex:20,
        pointerEvents:"none",
      }}>
        {[{l:"HOME",icon:"⊞",c:"#3b82f6",active:false},{l:"STREAM",icon:"◉",c:"#f43f5e",active:true}].map(n=>(
          <div key={n.l} style={{
            ...glass.navBtn(n.active, n.c),
            borderRadius:16,
            padding:"10px 16px",
            display:"flex",flexDirection:"column",alignItems:"center",gap:3,
            minWidth:60,
          }}>
            <span style={{color:n.active?n.c:"rgba(148,163,184,0.6)",fontSize:16}}>{n.icon}</span>
            <span style={{color:n.active?n.c:"rgba(100,116,139,0.8)",fontSize:8,fontWeight:800,letterSpacing:"0.14em",textTransform:"uppercase"}}>{n.l}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
