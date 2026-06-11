from project import db
from project.db_models.base_model import DBBaseModel


class Role(DBBaseModel):
    __tablename__ = 'roles'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(512), nullable=False)
    module = db.Column(db.String(512), nullable=False)
    permission_type = db.Column(db.String(32), nullable=False)

    def __init__(self, name, module, permission_type):
        self.name = name
        self.module = module
        self.permission_type = permission_type

    def to_dict(self):
        return dict(id=self.id, name=self.name, module=self.module, permission_type=self.permission_type)
