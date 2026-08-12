import React, { useEffect, useState } from 'react'
import { api, setCsrf } from './api.js'

export default function AuthGate({ children }) {
  const [state,setState]=useState(null), [user,setUser]=useState('admin'), [password,setPassword]=useState(''), [confirm,setConfirm]=useState(''), [err,setErr]=useState('')
  const load=async()=>{ try { const s=await api.authStatus(); if(s.csrf)setCsrf(s.csrf); setState(s) } catch(e){setErr(e.message)} }
  useEffect(()=>{load()},[])
  const submit=async(e)=>{e.preventDefault();setErr('');try{
    let r
    if(!state.configured){ if(password!==confirm) throw new Error('Passwords do not match'); r=await api.authSetup(user,password) }
    else r=await api.authLogin(user,password)
    setCsrf(r.csrf); await load()
  }catch(e){setErr(e.message)}}
  if(!state) return <div style={{padding:32}}>Loading…</div>
  if(state.authenticated) return children
  return <div style={{minHeight:'100vh',display:'grid',placeItems:'center',background:'var(--bg)'}}>
    <form onSubmit={submit} style={{width:360,maxWidth:'90vw',padding:28,border:'1px solid var(--border)',borderRadius:16,background:'var(--panel)',boxShadow:'0 18px 60px #0003'}}>
      <h2 style={{marginTop:0}}>VoWiFi Gateway</h2>
      <p style={{color:'var(--text-dim)'}}>{state.configured?'Administrator login':'Create the administrator account'}</p>
      <label>Username<input value={user} onChange={e=>setUser(e.target.value)} autoComplete="username" style={{width:'100%',boxSizing:'border-box',margin:'6px 0 14px',padding:10}}/></label>
      <label>Password<input type="password" value={password} onChange={e=>setPassword(e.target.value)} autoComplete={state.configured?'current-password':'new-password'} style={{width:'100%',boxSizing:'border-box',margin:'6px 0 14px',padding:10}}/></label>
      {!state.configured&&<label>Confirm password<input type="password" value={confirm} onChange={e=>setConfirm(e.target.value)} autoComplete="new-password" style={{width:'100%',boxSizing:'border-box',margin:'6px 0 14px',padding:10}}/></label>}
      {err&&<div style={{color:'#ef4444',marginBottom:12}}>{err}</div>}
      <button type="submit" style={{width:'100%',padding:11,border:0,borderRadius:9,background:'#2563eb',color:'#fff',fontWeight:700}}>{state.configured?'Sign in':'Create administrator'}</button>
    </form>
  </div>
}
