"""账户管理页面"""
import streamlit as st
from services.account_service import AccountService

svc = AccountService()

st.title("👤 账户管理")

# 新增账户
with st.expander("+ 新增账户", expanded=False):
    with st.form("new_account_form"):
        name = st.text_input("账户名称", placeholder="如: 普通账户、融资融券账户")
        acc_type = st.selectbox("账户类型", ["普通账户", "融资融券账户"])
        broker = st.text_input("券商名称（可选）", placeholder="如: 华泰证券")
        notes = st.text_area("备注（可选）")
        submitted = st.form_submit_button("保存")
        if submitted:
            if not name.strip():
                st.error("请输入账户名称")
            else:
                try:
                    svc.create(name.strip(), acc_type, broker.strip(), notes.strip())
                    st.success(f"账户「{name}」创建成功")
                    st.rerun()
                except Exception as e:
                    if "UNIQUE" in str(e):
                        st.error("账户名称已存在")
                    else:
                        st.error(f"创建失败: {e}")

# 账户列表
accounts = svc.list_all()
if not accounts:
    st.info("暂无账户，请先创建账户")
else:
    for acc in accounts:
        with st.container(border=True):
            col1, col2, col3 = st.columns([3, 1, 1])
            with col1:
                status = "🟢" if acc["is_active"] else "🔴"
                st.subheader(f"{status} {acc['account_name']}")
                st.caption(f"类型: {acc['account_type']} | 券商: {acc['broker'] or '未设置'}")
                if acc["notes"]:
                    st.caption(f"备注: {acc['notes']}")
            with col2:
                if acc["is_active"]:
                    if st.button("停用", key=f"deactivate_{acc['id']}"):
                        svc.update(acc["id"], is_active=0)
                        st.rerun()
                else:
                    if st.button("启用", key=f"activate_{acc['id']}"):
                        svc.update(acc["id"], is_active=1)
                        st.rerun()
            with col3:
                if st.button("删除", key=f"del_{acc['id']}"):
                    svc.delete(acc["id"])
                    st.success(f"账户「{acc['account_name']}」已删除")
                    st.rerun()
