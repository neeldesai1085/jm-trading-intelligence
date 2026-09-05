from sqlalchemy import select
from sqlalchemy.orm import Session
from fastapi import HTTPException
from app.models.entities import Portfolio

def ensure_default_portfolio(db:Session,user_id:int):
    p=db.scalar(select(Portfolio).where(Portfolio.user_id==user_id,Portfolio.is_default.is_(True)))
    if p:return p
    p=Portfolio(user_id=user_id,name='Main Portfolio',is_default=True);db.add(p);db.commit();db.refresh(p);return p

def get_user_portfolio(db:Session,user_id:int,portfolio_id:int|None):
    q=select(Portfolio).where(Portfolio.user_id==user_id)
    if portfolio_id is not None:q=q.where(Portfolio.id==portfolio_id)
    p=db.scalar(q.order_by(Portfolio.is_default.desc(),Portfolio.id))
    if not p:raise HTTPException(404,'Portfolio not found')
    return p

def get_user_portfolios(db:Session,user_id:int): return db.scalars(select(Portfolio).where(Portfolio.user_id==user_id).order_by(Portfolio.is_default.desc(),Portfolio.id)).all()
