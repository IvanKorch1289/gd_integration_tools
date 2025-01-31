from pydantic import BaseModel


class OrderCreatedEvent(BaseModel):
    order_id: str
    email: str


class OrderSendingSKBEvent(BaseModel):
    order_id: str
    email: str


class EmailSendEvent(BaseModel):
    email: str
    subject: str
    message: str
