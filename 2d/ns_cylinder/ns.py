from dolfin import *
from math import atan2
import numpy as np
import scipy.sparse as sps
import scipy.sparse.linalg as sla
import scipy.io as sio

# position of blowing/suction slots
# NOTE: This must be same as in the geo file.
thetac = 60.0   # location of slot center
thetaw = 10.0   # angular width of slot
xc     = 0.25   # center of cylinder

# Angular range of top slot [theta1, theta2]
theta1 = thetac - 0.5 * thetaw
theta2 = thetac + 0.5 * thetaw

# Parabolic initial condition, used as inlet bc
class initial_condition(Expression):
   def eval(self, value, x):
      value[0] = 1.5*(1.0 - (x[1]/0.2)*(x[1]/0.2))
      value[1] = 0.0
      value[2] = 0.0
      return value
   def value_shape(self):
      return (3,)

# Function defining the blowing velocity profile
def G(s):
    if s <= 0.0:
        return 0.0
    elif s >= 1.0:
        return 1.0
    else:
        return s**3 * (6.0*s**2 - 15.0*s + 10.0)

def g(theta,tc,tw):
    s = (theta - tc)/tw + 0.5
    return G(3.0*s) - G(3.0*(s-1.0)+1.0)

# Velocity at slot
class velocity(Expression):
    def __init__(self, u1=0.0, u2=0.0):
        self.u1 = u1
        self.u2 = u2

    def eval(self, value, x):
        xx  = x[0] - xc; yy = x[1]
        r   = sqrt(xx**2 + yy**2)
        nx  = xx/r
        ny  = yy/r
        ang = atan2(yy,xx) * 180.0/pi
        if (ang-theta1) > -1.0e-13 and (ang-theta2) < 1.0e-13:
            veln     = self.u1 * g(ang,thetac,thetaw)
            value[0] = veln * nx
            value[1] = veln * ny
        elif (ang+theta1) < 1.0e-13 and (ang+theta2) > -1.0e-13:
            veln     = self.u2 * g(ang,-thetac,thetaw)
            value[0] = veln * nx
            value[1] = veln * ny
        else:
            veln     = 0.0
            value[0] = 0.0
            value[1] = 0.0

    def value_shape(self):
        return (2,)

# Return velocity and pressure, where pressure is zero and not
# really used. Needed only to determine the control operator
# B. This function calls velocity and seems to be slow.
class allvar(Expression):
    def __init__(self, u1=0.0, u2=0.0):
        self.u1 = u1
        self.u2 = u2
        self.v  = velocity(u1, u2)

    def eval(self, value, x):
        vel = np.zeros(2)
        self.v.eval(vel,x)
        value[0] = vel[0]
        value[1] = vel[1]
        value[2] = 0.0

    def value_shape(self):
        return (3,)

class NSProblem():
    def __init__(self, Re, udeg):
        self.udeg = udeg
        self.Re   = Re
        self.D    = 0.1
        self.Uinf = 1.0

        self.mesh = Mesh("cylinder_in_channel.xml")
        boundaries = MeshFunction("size_t", self.mesh, "cylinder_in_channel_facet_region.xml")
        self.ds = Measure("ds")[boundaries]

        self.V = VectorFunctionSpace(self.mesh, "CG", udeg)
        self.Q = FunctionSpace(self.mesh, "CG", udeg-1)
        self.W = MixedFunctionSpace([self.V, self.Q])

        print "Reynolds number = ", Re
        print "Velocity dofs   = ", self.V.dim()
        print "Pressure dofs   = ", self.Q.dim()
        print "Total    dofs   = ", self.W.dim()

        # Define boundary conditions
        uinlet   = Expression(("1.5*(1.0 - (x[1]/0.2)*(x[1]/0.2))", "0"))
        inlet    = DirichletBC(self.W.sub(0), uinlet, boundaries, 1)
        side     = DirichletBC(self.W.sub(0), (0, 0), boundaries, 2)
        cyl      = DirichletBC(self.W.sub(0), (0, 0), boundaries, 4)
        self.vslot = velocity(0.0, 0.0)
        self.cont1    = DirichletBC(self.W.sub(0), self.vslot, boundaries, 5)
        self.cont2    = DirichletBC(self.W.sub(0), self.vslot, boundaries, 6)
        self.bcs = [inlet, side, cyl, self.cont1, self.cont2]

    def viscosity_coefficient(self):
        return Constant(self.D*self.Uinf/self.Re)

    def compute_forces(self, nu, u, p):
        # Stress tensor
        T = nu*(grad(u) + grad(u).T) - p*Identity(2)
        # Face normals
        n = FacetNormal(self.mesh)

        # Compute force on cylinder
        drag = -T[0,j]*n[j]*self.ds(4) - T[0,j]*n[j]*self.ds(5) - T[0,j]*n[j]*self.ds(6)
        lift = -T[1,j]*n[j]*self.ds(4) - T[1,j]*n[j]*self.ds(5) - T[1,j]*n[j]*self.ds(6)
        drag = assemble(drag); lift = assemble(lift)
        return drag, lift

    def steady_state(self):
        # Define test functions
        (v,q) = TestFunctions(self.W)

        # Define trial functions
        w     = Function(self.W)
        (u,p) = (as_vector((w[0], w[1])), w[2])

        nu = self.viscosity_coefficient()

        # Weak form
        F =   inner(grad(u)*u, v)*dx        \
            + nu*inner(grad(u), grad(v))*dx \
            - p*div(v)*dx                   \
            - q*div(u)*dx

        # Derivative of weak form
        dw = TrialFunction(self.W)
        dF = derivative(F, w, dw)

        problem = NonlinearVariationalProblem(F, w, self.bcs, dF)
        solver  = NonlinearVariationalSolver(problem)
        # Set linear solver parameters
        itsolver = solver.parameters["newton_solver"]
        itsolver["absolute_tolerance"] = 1.0e-10
        itsolver["relative_tolerance"] = 1.0e-10

        # To see various solver options, uncomment following line
        #info(solver.parameters, True); quit()

        # Solve the problem
        solver.solve()

        # Save steady solution
        File("steady/steady.xml") << w.vector()

        # Save vtk for visualization
        (u,p) = w.split()
        print "Saving velocity.pvd"
        File("steady/velocity.pvd") << u
        print "Saving pressure.pvd"
        File("steady/pressure.pvd") << p

        # Compute and save vorticity in vtk format
        r = TrialFunction(self.Q)
        s = TestFunction(self.Q)
        a = r*s*dx
        L = (u[0].dx(1) - u[1].dx(0))*s*dx
        vort = Function(self.Q)
        solve(a == L, vort)
        print "Saving vorticity.pvd"
        File("steady/vorticity.pvd") << vort

        drag, lift = self.compute_forces(nu, u, p)
        print "Drag =", drag
        print "Lift =", lift

    def linear_system(self):
        parameters.linear_algebra_backend = "uBLAS"

        ups = Function(self.W)
        print "Reading stationary solution from file steady.xml"
        File("steady/steady.xml") >> ups.vector()
        us = as_vector((ups[0],ups[1]))

        # Define test functions
        (v,q) = TestFunctions(self.W)

        # Define trial functions
        (u,p) = TrialFunctions(self.W)

        nu = self.viscosity_coefficient()

        # Weak form
        F = - inner(grad(us)*u, v)*dx        \
            - inner(grad(u)*us, v)*dx        \
            - nu*inner(grad(u), grad(v))*dx \
            + p*div(v)*dx                   \
            + q*div(u)*dx

        Aa = assemble(F)

        # Convert to sparse format
        rows, cols, values = Aa.data()
        Aa = sps.csc_matrix((values, cols, rows))
        print "Size of Aa =",Aa.shape

        m  = inner(u,v)*dx
        Ma = assemble(m)

        # Convert to sparse format
        rows, cols, values = Ma.data()
        Ma = sps.csc_matrix((values, cols, rows))
        print "Size of Ma =",Ma.shape

        bcinds = []
        for bc in self.bcs:
            bcinds.extend(bc.get_boundary_values().keys())

        N = self.W.dim()
        freeinds = np.setdiff1d(range(N),bcinds,assume_unique=True).astype(np.int32)
        pinds = self.W.sub(1).dofmap().dofs()

        print "Writing free indices into freeinds.txt"
        f = open('freeinds.txt','w')
        for item in freeinds:
           f.write("%d\n" % item)
        f.close()

        print "Writing pressure indices into pinds.txt"
        f = open('pinds.txt','w')
        for item in pinds:
           f.write("%d\n" % item)
        f.close()        

        A = Aa[freeinds,:][:,freeinds]
        print "Size of A =",A.shape

        M = Ma[freeinds,:][:,freeinds]
        print "Size of M =",M.shape

        vinds1 = self.cont1.get_boundary_values().keys()
        vinds2 = self.cont2.get_boundary_values().keys()

        # Velocity control operator
        ua = interpolate(allvar(1.0,0.0),self.W)
        ua = ua.vector().array()
        Bv1= Aa[freeinds,:][:,vinds1].dot(ua[vinds1])
        print "Size of Bv1 =", Bv1.shape[0]

        ua = interpolate(allvar(0.0,1.0),self.W)
        ua = ua.vector().array()
        Bv2= Aa[freeinds,:][:,vinds2].dot(ua[vinds2])
        print "Size of Bv2 =", Bv2.shape[0]

        B = np.column_stack((Bv1,Bv2))
        print "Size of B =", B.shape[0]

        # Save matrices in matlab format
        print "Saving linear system into linear.mat"
        sio.savemat('linear.mat', mdict={'M':M, 'A':A, 'B':B}, oned_as='column')

        return

        # Compute eigenvalues/vectors of (A,M)
        print "Computing eigenvalues/vectors ..."
        sigma = 10.0
        vals, vecs = sla.eigs(A, k=200, M=M, sigma=sigma, which='LM', ncv=400, tol=1.0e-8)
        ii = np.argsort(vals)[::-1]
        fv = File("eigvtk/eig.pvd")
        up = Function(self.W)
        fe = open("eig.dat","w")
        for i in ii:
            vr, vi = np.real(vals[i]), np.imag(vals[i])
            print vr, vi
            fe.write(str(vr)+"  "+str(vi)+"\n")

            up.vector()[freeinds] = np.array(np.real(vecs[:,i]))
            u,p = up.split()
            fv << u

            up.vector()[freeinds] = np.array(np.imag(vecs[:,i]))
            u,p = up.split()
            fv << u

    def run_picard(self):
        """
        Flow over cylinder in channel
        Picard iteration on convective term
        BDF1 in first step, BDF2 subsequently
        """
        # Solution variables
        up0 = Function(self.W)  # u^{n-2}
        up1 = Function(self.W)  # u^{n-1}
        up2 = Function(self.W)  # u^{n}

        # Trial functions
        (u,p)  = TrialFunctions(self.W)

        # Test functions
        (v,q)  = TestFunctions(self.W)

        # These are used to estimate cfl number
        DG = FunctionSpace(self.mesh, 'DG', 0)
        vdg= TestFunction(DG)
        h    = [cell.diameter() for cell in cells(self.mesh)]
        area = [cell.volume()   for cell in cells(self.mesh)]

        nu = self.viscosity_coefficient()
        dt = 0.001; idt= Constant(1.0/dt)

        #up0.interpolate(initial_condition())
        File("steady/steady.xml") >> up0.vector()
        u0 = as_vector((up0[0], up0[1]))
        u1 = as_vector((up1[0], up1[1]))
        u2 = as_vector((up2[0], up2[1]))

        t, Tf, it  = 0.0, 10.0, 0
        fu = File("solvtk/u.pvd")

        # First time step: BDF1
        # Predicted velocity
        us = u0

        F1 = idt*inner(u - u0, v)*dx       \
            + inner(grad(us)*us, v)*dx      \
            - p*div(v)*dx                   \
            + nu*inner(grad(u), grad(v))*dx \
            - q*div(u)*dx

        a, L  = lhs(F1), rhs(F1)

        A  = PETScMatrix(); assemble(a, tensor=A)
        b  = assemble(L)
        [bc.apply(A,b) for bc in self.bcs]
        solver = LUSolver(A)
        solver.solve(up1.vector(), b)
        t += dt; it+= 1

        # Now switch to BDF2
        F2 = idt*inner(1.5*u - 2.0*u1 + 0.5*u0, v)*dx  \
            + inner(grad(u2)*u2, v)*dx                  \
            - p*div(v)*dx                               \
            + nu*inner(grad(u), grad(v))*dx             \
            - q*div(u)*dx

        a, L  = lhs(F2), rhs(F2)

        A  = assemble(a)
        [bc.apply(A) for bc in self.bcs]
        solver = LUSolver(A)
        solver.parameters['reuse_factorization'] = True

        while t < Tf:
            # estimate cfl number
            uavg = assemble(sqrt(u1[0]**2+u1[1]**2)*vdg*dx)
            uavg = uavg.array()/area
            cfl  = dt * max(uavg/h)

            # Picard iteration
            up2.vector()[:] = 2.0*up1.vector() - up0.vector()
            for i in range(4):
                b  = assemble(L)
                [bc.apply(b) for bc in self.bcs]
                res= A * up2.vector() - b
                res_norm = norm(res)/sqrt(self.W.dim())
                print "%3d %12.4e" % (i, res_norm)
                solver.solve(up2.vector(), b)

            up0.assign(up1)
            up1.assign(up2)
            t += dt; it+= 1
            print "it = %6d,   t = %12.6e,   cfl = %e" % (it,t,cfl)
            if cfl > 10.0:
                print "cfl is too large !!!"
                break
            if it%100 == 0:
                u,p = up2.split()
                fu << u

    def run_bdf_ext(self):
        # Solution variables
        up0 = Function(self.W)  # u^{n-2}
        up1 = Function(self.W)  # u^{n-1}
        up2 = Function(self.W)  # u^{n}

        # Trial functions
        u,p = TrialFunctions(self.W)

        # Test functions
        v,q = TestFunctions(self.W)

        # These are used to estimate cfl number
        DG   = FunctionSpace(self.mesh, 'DG', 0)
        vdg  = TestFunction(DG)
        h    = [cell.diameter() for cell in cells(self.mesh)]
        area = [cell.volume()   for cell in cells(self.mesh)]

        nu = self.viscosity_coefficient()
        dt = 0.01; idt= Constant(1.0/dt)

        #up0.interpolate(initial_condition())
        File("steady/steady.xml") >> up0.vector()
        u0 = as_vector((up0[0], up0[1]))
        u1 = as_vector((up1[0], up1[1]))
        u2 = as_vector((up2[0], up2[1]))

        t, Tf, it  = 0.0, 50.0, 0

        ffile = open('force.dat', 'w')
        cd, cl = self.compute_forces(nu, u0, up0[2])
        force=str(it)+" "+str(t)+" "+str(cl)+" "+str(cd)+"\n"
        ffile.write(force); ffile.flush()

        fu = File("solvtk/u.pvd")

        # First time step: BDF1
        F1 = idt*inner(u - u0, v)*dx       \
            + inner(grad(u)*u0, v)*dx      \
            - p*div(v)*dx                   \
            + nu*inner(grad(u), grad(v))*dx \
            - q*div(u)*dx

        a, L  = lhs(F1), rhs(F1)

        A  = PETScMatrix(); assemble(a, tensor=A)
        solver = LUSolver(A)

        b  = assemble(L)
        [bc.apply(A,b) for bc in self.bcs]
        solver.solve(up1.vector(), b)
        t += dt; it+= 1

        # Now switch to BDF2
        uext = 2.0*u1 - u0
        F2 = idt*inner(1.5*u - 2.0*u1 + 0.5*u0, v)*dx  \
            + inner(grad(u)*uext, v)*dx                  \
            - p*div(v)*dx                               \
            + nu*inner(grad(u), grad(v))*dx             \
            - q*div(u)*dx

        a, L  = lhs(F2), rhs(F2)

        # Following fails in v1.5, fix will come in v1.6
        #A  = PETScMatrix(); assemble(a, tensor=A)
        #solver = LUSolver(A)
        #solver.parameters['same_nonzero_pattern'] = True
        A  = PETScMatrix()

        while t < Tf:
            # estimate cfl number
            uavg = assemble(sqrt(u1[0]**2+u1[1]**2)*vdg*dx)
            uavg = uavg.array()/area
            cfl  = dt * max(uavg/h)

            assemble(a, tensor=A)
            assemble(L, tensor=b)
            [bc.apply(A,b) for bc in self.bcs]
            solver = LUSolver(A)
            solver.solve(up2.vector(), b)
            up0.assign(up1)
            up1.assign(up2)
            t += dt; it+= 1
            print "it = %6d,   t = %12.6e,   cfl = %12.3e" % (it,t,cfl)
            # Compute lift/drag and store in arrays
            cd, cl = self.compute_forces(nu, u2, up2[2])
            force=str(it)+" "+str(t)+" "+str(cl)+" "+str(cd)+"\n"
            ffile.write(force); ffile.flush()
            if cfl > 100.0:
                print "cfl is too large !!!"
                break
            if it%50 == 0:
                u,p = up2.split()
                fu << u
