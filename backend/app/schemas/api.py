from pydantic import BaseModel, Field
class RegisterRequest(BaseModel): name:str=Field(min_length=1,max_length=120); email:str; password:str=Field(min_length=8,max_length=256)
class LoginRequest(BaseModel): email:str; password:str
class PortfolioRequest(BaseModel): name:str=Field(min_length=1,max_length=120)
