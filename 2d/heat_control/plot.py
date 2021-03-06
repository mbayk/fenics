import numpy as np
import matplotlib.pyplot as plt

d = np.loadtxt('log.txt')

energy0 = d[0,2]
print('Initial energy = %e' % energy0)

plt.figure()
plt.semilogy(d[:,1],d[:,2]/energy0)
plt.xlabel('Time, t')
plt.ylabel('log(E(t)/E(0))')
plt.grid(True)
plt.savefig('energy.pdf')
print('Figure saved into file energy.pdf')

plt.figure()
plt.semilogy(d[:,1],d[:,3])
plt.xlabel('Time, t')
plt.ylabel('Norm of control')
plt.grid(True)
plt.savefig('control.pdf')
print('Figure saved into file control.pdf')

plt.show()
